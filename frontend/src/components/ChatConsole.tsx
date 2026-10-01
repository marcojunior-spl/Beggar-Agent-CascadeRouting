import React, { useState, useRef, useEffect } from 'react';
import { MensagemChat, ProvedorLLM } from '../types';
import { Send, Bot, AlertTriangle, RefreshCw, Sparkles, Download, XCircle } from 'lucide-react';

interface ChatConsoleProps {
  mensagens: MensagemChat[];
  provedores: ProvedorLLM[];
  onEnviarMensagem: (texto: string) => Promise<void>;
  onExportar: () => void;
  isProcessando: boolean;
  etapaAtual?: string | null;
}

export const ChatConsole: React.FC<ChatConsoleProps> = ({
  mensagens,
  provedores,
  onEnviarMensagem,
  onExportar,
  isProcessando,
  etapaAtual,
}) => {
  const [inputTexto, setInputTexto] = useState('');
  const [motivoExpandido, setMotivoExpandido] = useState<string | null>(null);
  const finalMensagensRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    finalMensagensRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [mensagens, etapaAtual]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputTexto.trim() || isProcessando) return;
    const texto = inputTexto;
    setInputTexto('');
    await onEnviarMensagem(texto);
  };

  const handleExemploClick = (exemplo: string) => {
    setInputTexto(exemplo);
  };

  return (
    <div
      id="painel-chat-console"
      className="bg-slate-900 border border-slate-800 rounded-xl flex flex-col h-[560px] shadow-sm"
    >
      {/* Header */}
      <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"></div>
          <div>
            <h3 className="text-sm font-semibold text-slate-100">Sessão Interativa do Agente</h3>
            <p className="text-[11px] text-slate-400">
              Experimente prompts e observe a orquestração de fallback em tempo real
            </p>
          </div>
        </div>

        <div className="hidden sm:flex items-center gap-2">
          <button
            type="button"
            onClick={onExportar}
            disabled={isProcessando || mensagens.length === 0}
            title="Exportar conversa atual como Markdown"
            className="flex items-center gap-1 text-[11px] text-slate-300 hover:text-slate-100 bg-slate-800/80 hover:bg-slate-700 border border-slate-700/80 px-2 py-1 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Download className="w-3 h-3" />
            <span>Exportar .md</span>
          </button>

          <div className="flex items-center gap-2 text-xs font-mono bg-slate-800/80 px-2.5 py-1 rounded border border-slate-700/80 text-slate-300">
            <span className="text-slate-400">Primeiro na Fila:</span>
            <span className="text-indigo-300 font-semibold">{provedores[0]?.nome || 'Nenhum'}</span>
          </div>
        </div>
      </div>

      {/* Área de Mensagens */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {mensagens.map((msg) => (
          <div
            key={msg.id}
            id={`mensagem-${msg.id}`}
            className={`flex flex-col ${msg.remetente === 'usuario' ? 'items-end' : 'items-start'}`}
          >
            <div
              className={`max-w-[88%] rounded-xl px-4 py-3 text-sm ${
                msg.remetente === 'usuario'
                  ? 'bg-indigo-600 text-white rounded-br-none shadow-sm'
                  : 'bg-slate-800/90 border border-slate-700/80 text-slate-200 rounded-bl-none shadow-sm'
              }`}
            >
              {/* Cabeçalho de metadados da mensagem do agente */}
              {msg.remetente === 'agente' && (
                <div className="mb-2 pb-2 border-b border-slate-700/70 flex flex-wrap items-center justify-between gap-2 text-[11px]">
                  <div className="flex items-center gap-1.5 font-medium flex-wrap">
                    <Bot className="w-3.5 h-3.5 text-indigo-400" />
                    <span className="text-slate-300">
                      Respondido por:{' '}
                      <strong className="text-emerald-400">{msg.modeloUtilizado}</strong>
                    </span>
                    {msg.nivelComplexidade && (
                      <button
                        type="button"
                        onClick={() =>
                          setMotivoExpandido((atual) => (atual === msg.id ? null : msg.id))
                        }
                        className="ml-1 text-[9px] uppercase tracking-wide px-1.5 py-0.2 rounded bg-slate-700/70 hover:bg-slate-600/70 text-slate-300 transition-colors"
                        title={
                          msg.motivoComplexidade
                            ? 'Clique para ver por que o roteador escolheu este nível'
                            : 'Nível de complexidade detectado pelo roteador'
                        }
                      >
                        {msg.nivelComplexidade}
                        {msg.motivoComplexidade ? ' ▾' : ''}
                      </button>
                    )}
                  </div>
                  {msg.duracaoSegundos != null && (
                    <span className="text-slate-400 font-mono text-[10px]">
                      {msg.duracaoSegundos}s
                    </span>
                  )}
                </div>
              )}

              {/* Painel "explicar decisão" */}
              {msg.remetente === 'agente'
                && msg.motivoComplexidade
                && motivoExpandido === msg.id && (
                  <div className="mb-2.5 p-2 rounded bg-sky-950/40 border border-sky-800/60 text-sky-200 text-[11px] leading-relaxed">
                    <div className="flex items-center gap-1.5 font-semibold text-sky-300 mb-1">
                      🧭 Por que este nível?
                    </div>
                    {msg.motivoComplexidade}
                  </div>
                )}

              {/* Bloco de fallback: VERDE se sucesso, VERMELHO se falha total */}
              {msg.remetente === 'agente'
                && msg.fallbackAcionado
                && msg.modelosFalhados
                && msg.modelosFalhados.length > 0 && (
                  msg.sucesso === false ? (
                    <div className="mb-2.5 p-2 rounded bg-rose-950/40 border border-rose-800/60 text-rose-200 text-xs">
                      <div className="flex items-center gap-1.5 font-semibold text-rose-300 mb-1">
                        <XCircle className="w-3.5 h-3.5 text-rose-400" />
                        Falha Total — Nenhum Provedor Respondeu
                      </div>
                      <ul className="space-y-0.5 text-[11px] text-rose-200/80 pl-5 list-disc">
                        {msg.modelosFalhados.map((falha, idx) => (
                          <li key={idx}>
                            <strong>{falha.nome}</strong> falhou ({falha.categoria}
                            {falha.codigoHttp ? ` - Código ${falha.codigoHttp}` : ''}).
                          </li>
                        ))}
                      </ul>
                      <div className="mt-1 text-[11px] text-rose-300 font-medium">
                        ⚠️ A mensagem exibida é um erro fatal, não uma resposta do agente.
                      </div>
                    </div>
                  ) : (
                    <div className="mb-2.5 p-2 rounded bg-amber-950/40 border border-amber-800/60 text-amber-200 text-xs">
                      <div className="flex items-center gap-1.5 font-semibold text-amber-300 mb-1">
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                        Fallback Automático Executado com Sucesso
                      </div>
                      <ul className="space-y-0.5 text-[11px] text-amber-200/80 pl-5 list-disc">
                        {msg.modelosFalhados.map((falha, idx) => (
                          <li key={idx}>
                            <strong>{falha.nome}</strong> falhou ({falha.categoria}
                            {falha.codigoHttp ? ` - Código ${falha.codigoHttp}` : ''}).
                          </li>
                        ))}
                      </ul>
                      <div className="mt-1 text-[11px] text-emerald-300 font-medium">
                        ➡️ A requisição foi recuperada e finalizada por{' '}
                        <strong>{msg.modeloUtilizado}</strong>.
                      </div>
                    </div>
                  )
                )}

              {/* Conteúdo da Mensagem */}
              <div className="whitespace-pre-wrap leading-relaxed text-sm">{msg.conteudo}</div>
            </div>

            <span className="text-[10px] text-slate-500 mt-1 px-1">{msg.timestamp}</span>
          </div>
        ))}

        {/* Indicador de Processamento / Etapa em Execução */}
        {isProcessando && (
          <div className="flex items-start gap-2 text-xs">
            <div className="w-7 h-7 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-indigo-400 animate-spin">
              <RefreshCw className="w-3.5 h-3.5" />
            </div>
            <div className="bg-slate-800/90 border border-slate-700/80 rounded-lg px-3.5 py-2.5 text-slate-300 max-w-[85%]">
              <div className="flex items-center gap-2 font-medium text-indigo-300">
                <span>Orquestrando chamada ao modelo...</span>
              </div>
              {etapaAtual && (
                <div className="mt-1 text-slate-400 font-mono text-[11px] whitespace-pre-wrap">
                  {etapaAtual}
                </div>
              )}
            </div>
          </div>
        )}

        <div ref={finalMensagensRef} />
      </div>

      {/* Prompts de Demonstração Rápida */}
      <div className="px-4 py-2 bg-slate-950/50 border-t border-slate-800/80 flex items-center gap-2 overflow-x-auto text-[11px]">
        <span className="text-slate-400 flex items-center gap-1 font-medium flex-shrink-0">
          <Sparkles className="w-3 h-3 text-amber-400" /> Teste rápido:
        </span>
        <button
          type="button"
          onClick={() => handleExemploClick('oi')}
          className="px-2.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors whitespace-nowrap"
        >
          &quot;oi&quot; (teste do seu log)
        </button>
        <button
          type="button"
          onClick={() => handleExemploClick('Crie uma função em Python para leitura segura de arquivo.')}
          className="px-2.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors whitespace-nowrap"
        >
          &quot;Leitura de arquivos Python&quot;
        </button>
        <button
          type="button"
          onClick={() => handleExemploClick('Como o fallback garante alta disponibilidade em sistemas de IA?')}
          className="px-2.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors whitespace-nowrap"
        >
          &quot;Conceito de Fallback LLM&quot;
        </button>
      </div>

      {/* Campo de Input */}
      <form
        onSubmit={handleSubmit}
        className="p-3 border-t border-slate-800 flex items-center gap-2 bg-slate-900"
      >
        <input
          id="input-prompt-chat"
          type="text"
          value={inputTexto}
          onChange={(e) => setInputTexto(e.target.value)}
          placeholder="Digite um prompt para o agente..."
          disabled={isProcessando}
          className="flex-1 bg-slate-950 border border-slate-700 rounded-lg px-3.5 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 disabled:opacity-50"
        />
        <button
          id="btn-enviar-prompt"
          type="submit"
          disabled={isProcessando || !inputTexto.trim()}
          className="bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white font-medium px-4 py-2 rounded-lg text-sm flex items-center gap-1.5 transition-colors shadow-sm"
        >
          <Send className="w-3.5 h-3.5" />
          <span>Enviar</span>
        </button>
      </form>
    </div>
  );
};