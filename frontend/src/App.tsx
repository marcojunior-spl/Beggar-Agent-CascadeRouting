import React, { useEffect, useState, useCallback, useRef } from 'react';
import { ProvedorLLM, DiagnosticoFalha, MensagemChat } from './types';
import { ProviderChain } from './components/ProviderChain';
import { ChatConsole } from './components/ChatConsole';
import { DiagnosticLogs } from './components/DiagnosticLogs';
import {
  api,
  LogApi,
  HistoricoMensagemApi,
  enviarMensagemStreaming,
  EventoStreaming,
  RespostaChatApi,
} from './api/client';
import {
  ShieldAlert,
  MessageSquare,
  Terminal,
  Activity,
  AlertTriangle,
  RefreshCw,
} from 'lucide-react';

/**
 * Componente raiz do frontend.
 *
 * Conversa de verdade com o backend Python via `api` (src/api/client.ts),
 * usando o endpoint SSE /api/chat/stream para mostrar o progresso da
 * orquestração em tempo real (tentativa → retry → fallback → resposta).
 *
 * A sessão é identificada por um `sessao_id` (uuid) persistido em localStorage.
 * O histórico persistido (SQLite no backend) é carregado ao montar.
 */

const CHAVE_SESSAO = 'agente_sessao_id';

function obterOuCriarSessaoId(): string {
  try {
    const existente = localStorage.getItem(CHAVE_SESSAO);
    if (existente) return existente;
    const novo = (crypto.randomUUID?.() ?? `sessao-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    localStorage.setItem(CHAVE_SESSAO, novo);
    return novo;
  } catch {
    // localStorage indisponível (modo restrito): gera id efêmero por sessão
    return `sessao-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

function logApiParaDiagnostico(log: LogApi, index: number): DiagnosticoFalha {
  return {
    id: `log-${index}-${log.timestamp}`,
    timestamp: log.timestamp,
    modeloNome: log.modelo,
    modelId: log.model_id,
    codigoHttp: log.codigo_http,
    categoria: log.categoria,
    motivoAmigavel: log.motivo,
    sugestao: log.sugestao,
    detalhesBrutos: log.erro_bruto,
    proximoModelo: null,
    duracaoSegundos: log.duracao_segundos,
  };
}

function historicoParaMensagem(h: HistoricoMensagemApi): MensagemChat {
  const timestamp = (() => {
    try {
      return new Date(h.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return h.timestamp;
    }
  })();
  return {
    id: `hist-${h.id}`,
    remetente: h.remetente,
    conteudo: h.conteudo,
    timestamp,
    modeloUtilizado: h.modelo_utilizado ?? undefined,
    nivelComplexidade: h.nivel_complexidade ?? undefined,
    motivoComplexidade: h.motivo_complexidade ?? undefined,
    fallbackAcionado: Boolean(h.fallback_acionado),
    duracaoSegundos: h.duracao_segundos ?? undefined,
  };
}

export default function App() {
  const [sessaoId] = useState<string>(() => obterOuCriarSessaoId());

  const [provedores, setProvedores] = useState<ProvedorLLM[]>([]);
  const [provedoresCarregando, setProvedoresCarregando] = useState(true);
  const [provedoresErro, setProvedoresErro] = useState<string | null>(null);

  const [logs, setLogs] = useState<DiagnosticoFalha[]>([]);
  const [abaAtiva, setAbaAtiva] = useState<'chat' | 'logs'>('chat');
  const [isProcessando, setIsProcessando] = useState(false);
  const [etapaAtual, setEtapaAtual] = useState<string | null>(null);
  const [provedorExecutandoNome, setProvedorExecutandoNome] = useState<string | null>(null);
  const [backendOffline, setBackendOffline] = useState(false);

  const logStreamingRef = useRef<string[]>([]);

  const [mensagens, setMensagens] = useState<MensagemChat[]>([
    {
      id: 'msg-boas-vindas',
      remetente: 'agente',
      conteudo:
        'Olá! Sou o seu Agente Resiliente Híbrido.\n\nEstou equipado com uma esteira de modelos (Google Gemini, Groq, OpenRouter, e mais) com roteamento por complexidade, detecção de erros HTTP (404, 429, 401, 5xx) e fallback automático. As mensagens são transmitidas em tempo real — você vê cada tentativa conforme acontece.',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      fallbackAcionado: false,
    },
  ]);

  const carregarProvedores = useCallback(async () => {
    setProvedoresCarregando(true);
    setProvedoresErro(null);
    try {
      const dados = await api.listarProvedores();
      setProvedores(dados as ProvedorLLM[]);
      setBackendOffline(false);
    } catch (e) {
      setProvedoresErro(e instanceof Error ? e.message : 'Erro desconhecido');
      setBackendOffline(true);
    } finally {
      setProvedoresCarregando(false);
    }
  }, []);

  const carregarLogs = useCallback(async () => {
    try {
      const dados = await api.listarLogs(50);
      setLogs(dados.map(logApiParaDiagnostico));
    } catch {
      // Se o backend estiver fora do ar, simplesmente não atualiza a lista de logs.
    }
  }, []);

  const carregarHistorico = useCallback(async () => {
    try {
      const dados = await api.listarHistorico(sessaoId, 100);
      if (dados.length > 0) {
        setMensagens((prev) => {
          // Mantém a msg de boas-vindas apenas se o histórico estiver vazio.
          const base = prev.filter((m) => m.id !== 'msg-boas-vindas');
          return [...base, ...dados.map(historicoParaMensagem)];
        });
      }
    } catch {
      // silencioso — histórico é nice-to-have
    }
  }, [sessaoId]);

  useEffect(() => {
    carregarProvedores();
    carregarLogs();
    carregarHistorico();
  }, [carregarProvedores, carregarLogs, carregarHistorico]);

  const handleLimparLogs = async () => {
    try {
      await api.limparLogs();
      setLogs([]);
    } catch (e) {
      console.error('Falha ao limpar logs:', e);
    }
  };
    /**
   * Exporta o histórico da sessão atual como arquivo .md (download direto no
   * navegador — não precisa de endpoint de backend porque /api/historico/
   * já devolve tudo).
   */
  const handleExportarConversa = useCallback(async () => {
    try {
      const historico = await api.listarHistorico(sessaoId, 500);
      if (historico.length === 0) {
        alert('Não há mensagens nesta sessão para exportar.');
        return;
      }

      const linhas: string[] = [];
      linhas.push(`# Conversa — Agente Resiliente LLM`);
      linhas.push(``);
      linhas.push(`- **Sessão:** \`${sessaoId}\``);
      linhas.push(`- **Exportado em:** ${new Date().toLocaleString()}`);
      linhas.push(`- **Total de mensagens:** ${historico.length}`);
      linhas.push(``);
      linhas.push(`---`);
      linhas.push(``);

      for (const msg of historico) {
        const ehUsuario = msg.remetente === 'usuario';
        linhas.push(ehUsuario ? `## 👤 Você` : `## 🤖 Agente`);
        linhas.push(``);

        if (!ehUsuario) {
          const meta: string[] = [];
          if (msg.modelo_utilizado) meta.push(`**Modelo:** ${msg.modelo_utilizado}`);
          if (msg.nivel_complexidade) meta.push(`**Complexidade:** ${msg.nivel_complexidade}`);
          if (msg.duracao_segundos != null) meta.push(`**Duração:** ${msg.duracao_segundos}s`);
          if (msg.fallback_acionado) meta.push(`**Fallback acionado:** sim`);
          if (meta.length > 0) {
            linhas.push(meta.join(' · '));
            linhas.push(``);
          }
          if (msg.nivel_complexidade && msg.motivo_complexidade) {
            linhas.push(`> 🧭 *${msg.motivo_complexidade}*`);
            linhas.push(``);
          }
        }

        linhas.push(msg.conteudo);
        linhas.push(``);
      }

      const conteudo = linhas.join('\n');
      const blob = new Blob([conteudo], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `conversa-${sessaoId.slice(0, 8)}-${new Date().toISOString().slice(0, 10)}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('Falha ao exportar conversa:', e);
      alert('Não foi possível exportar a conversa. Verifique se o backend está rodando.');
    }
  }, [sessaoId]);

  /**
   * Traduz cada evento SSE em uma linha de "atividade" mostrada em etapaAtual.
   * Não criamos a mensagem final até chegar o evento `final` — o texto do
   * FinalAnswerStep é a resposta polida, enquanto os step_* são o raciocínio
   * interno (código/observações) que não é o que o usuário quer ver na bolha.
   */
  const handleEventoStreaming = useCallback((evt: EventoStreaming) => {
    const append = (linha: string) => {
      logStreamingRef.current.push(linha);
      // Limita a janela para evitar UI com log gigante
      if (logStreamingRef.current.length > 20) {
        logStreamingRef.current = logStreamingRef.current.slice(-20);
      }
      setEtapaAtual(logStreamingRef.current.join('\n'));
    };

    switch (evt.tipo) {
      case 'classificacao':
        append(`🧭 Complexidade: ${String(evt.nivel).toUpperCase()} — ${evt.motivo ?? ''}`);
        break;
      case 'tentativa':
        setProvedorExecutandoNome(evt.modelo ?? null);
        append(
          `${evt.eh_local ? '🏠' : evt.eh_fallback ? '🔄' : '🚀'} Tentando ${evt.modelo} (${(evt.indice ?? 0) + 1}/${evt.total ?? '?'})`,
        );
        break;
      case 'step_planejamento':
        append('🧠 Planejando...');
        break;
      case 'step_raciocinio':
        // Só reporta que um passo de raciocínio aconteceu — não despejamos o
        // código/cadeia de pensamento completa na UI (ficaria ilegível).
        append('💭 Raciocinando...');
        break;
      case 'step_observacao':
        append('👁️ Observação registrada');
        break;
      case 'step_erro':
        append(`⚠️ Erro no step: ${String(evt.texto).slice(0, 80)}...`);
        break;
      case 'falha':
        append(`❌ ${evt.log?.modelo ?? 'provedor'} falhou: ${evt.log?.categoria ?? ''}`);
        break;
      case 'retry':
        append(`⏳ Retry em ${evt.espera_segundos}s (${evt.modelo})`);
        break;
      case 'sucesso':
        append(`✅ Resposta de ${evt.modelo} (${evt.duracao}s)`);
        break;
      case 'timeout_global':
        append(`⏱️ ${evt.mensagem}`);
        break;
      case 'erro_fatal':
        append(`💥 ${evt.mensagem}`);
        break;
      case 'final':
        // nada aqui — tratado pela promise
        break;
      default:
        break;
    }
  }, []);

  const handleEnviarMensagem = async (texto: string) => {
    const timestampEnvio = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const userMsg: MensagemChat = {
      id: `user-${Date.now()}`,
      remetente: 'usuario',
      conteudo: texto,
      timestamp: timestampEnvio,
    };

    setMensagens((prev) => [...prev, userMsg]);
    setIsProcessando(true);
    logStreamingRef.current = [];
    setEtapaAtual('Conectando ao backend...');
    setProvedorExecutandoNome(null);

    try {
      const resultado: RespostaChatApi = await enviarMensagemStreaming(
        texto,
        sessaoId,
        handleEventoStreaming,
      );

      const agenteMsg: MensagemChat = {
        id: `agent-${Date.now()}`,
        remetente: 'agente',
        sucesso: resultado.sucesso,
        conteudo: resultado.resposta,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        modeloUtilizado: resultado.modelo_final || 'Nenhum (todos falharam)',
        fallbackAcionado: resultado.fallback_acionado,
        modelosFalhados: resultado.modelos_falhados.map((m) => ({
          nome: m.nome,
          categoria: m.categoria,
          codigoHttp: m.codigo_http,
        })),
        duracaoSegundos: resultado.duracao_segundos ?? undefined,
        nivelComplexidade: resultado.nivel_complexidade ?? undefined,
        motivoComplexidade: resultado.motivo_complexidade ?? undefined,
      };
      setMensagens((prev) => [...prev, agenteMsg]);

      carregarProvedores();
      carregarLogs();
    } catch (e) {
      const mensagemErro = e instanceof Error ? e.message : 'Erro desconhecido ao contatar o backend.';
      const erroMsg: MensagemChat = {
        id: `agent-error-${Date.now()}`,
        remetente: 'agente',
        conteudo: `❌ Não foi possível obter resposta do backend: ${mensagemErro}\n\nVerifique se o servidor Python está rodando (veja README.md).`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        fallbackAcionado: false,
      };
      setMensagens((prev) => [...prev, erroMsg]);
    } finally {
      setIsProcessando(false);
      setEtapaAtual(null);
      setProvedorExecutandoNome(null);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-indigo-600 selection:text-white">
      <header className="border-b border-slate-800/80 bg-slate-900/90 backdrop-blur sticky top-0 z-30 px-4 sm:px-6 py-3">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-indigo-600 flex items-center justify-center text-white shadow-md shadow-indigo-600/30">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-bold text-slate-100 tracking-tight">
                  Agente Resiliente LLM
                </h1>
                <span className="text-[10px] font-semibold uppercase tracking-wider bg-emerald-950 text-emerald-300 border border-emerald-800/60 px-2 py-0.5 rounded-full">
                  Alta Disponibilidade
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Orquestrador multi-provedor com roteamento por complexidade, streaming SSE e fallback transparente
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800 self-start sm:self-auto">
            <button
              id="tab-chat"
              onClick={() => setAbaAtiva('chat')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                abaAtiva === 'chat'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
              }`}
            >
              <MessageSquare className="w-3.5 h-3.5" />
              <span>Console & Chat</span>
            </button>

            <button
              id="tab-logs"
              onClick={() => setAbaAtiva('logs')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                abaAtiva === 'logs'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
              }`}
            >
              <Terminal className="w-3.5 h-3.5" />
              <span>Logs & Diagnóstico</span>
              {logs.length > 0 && (
                <span className="bg-rose-600 text-white text-[10px] px-1.5 py-0.2 rounded-full font-bold">
                  {logs.length}
                </span>
              )}
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-7xl mx-auto w-full p-4 sm:p-6 space-y-5">
        {backendOffline && (
          <div className="bg-rose-950/40 border border-rose-800/60 rounded-xl p-4 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
            <div className="text-sm text-rose-200">
              <p className="font-semibold">Não foi possível conectar ao backend.</p>
              <p className="text-rose-300/80 text-xs mt-1">
                Verifique se o servidor Python (FastAPI) está rodando. Veja o README.md do projeto
                para instruções de como iniciar o backend.
              </p>
            </div>
            <button
              onClick={carregarProvedores}
              className="ml-auto flex items-center gap-1.5 text-xs text-rose-200 bg-rose-900/60 hover:bg-rose-900 px-2.5 py-1.5 rounded border border-rose-800"
            >
              <RefreshCw className="w-3 h-3" />
              Tentar novamente
            </button>
          </div>
        )}

        <ProviderChain
          provedores={provedores}
          provedorExecutandoNome={provedorExecutandoNome}
          carregando={provedoresCarregando}
          erro={provedoresErro}
        />

        {abaAtiva === 'chat' && (
          <ChatConsole
            mensagens={mensagens}
            provedores={provedores as any}
            onEnviarMensagem={handleEnviarMensagem}
            onExportar={handleExportarConversa}  
            isProcessando={isProcessando}
            etapaAtual={etapaAtual}
          />
        )}

        {abaAtiva === 'logs' && (
          <DiagnosticLogs logs={logs as any} onLimparLogs={handleLimparLogs} />
        )}
      </main>

      <footer className="border-t border-slate-800/80 bg-slate-900/50 py-3 px-4 text-xs text-slate-500">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2 text-center sm:text-left">
          <span className="flex items-center gap-1.5">
            <Activity className="w-3.5 h-3.5 text-emerald-400" />
            Backend Python real (FastAPI) • Streaming SSE ativo • Sessão {sessaoId.slice(0, 8)}
          </span>
        </div>
      </footer>
    </div>
  );
}