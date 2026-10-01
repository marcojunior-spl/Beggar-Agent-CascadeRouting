/**
 * Cliente da API do backend (FastAPI).
 *
 * Para um dev júnior:
 * - Todas as chamadas usam caminhos relativos como '/api/chat'. Em desenvolvimento,
 *   o Vite redireciona isso para o backend (veja vite.config.ts -> server.proxy).
 * - Em produção (build final servido por algum servidor estático), configure
 *   esse mesmo servidor para fazer proxy de /api para o backend, ou defina
 *   VITE_API_BASE_URL no .env do frontend para apontar direto para a URL do backend.
 * - `enviarMensagemStreaming` consome SSE via fetch + ReadableStream (EventSource
 *   só suporta GET nativamente, e nosso endpoint é POST).
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export interface ModeloFalhadoApi {
  nome: string;
  categoria: string;
  codigo_http: number | null;
}

export interface RespostaChatApi {
  sucesso: boolean;
  resposta: string;
  modelo_final: string | null;
  fallback_acionado: boolean;
  modelos_tentados: string[];
  modelos_falhados: ModeloFalhadoApi[];
  duracao_segundos: number | null;
  nivel_complexidade: string | null;
  motivo_complexidade: string | null; 
  tempo_total_segundos?: number | null;
}

export interface ProvedorApi {
  id: string;
  nome: string;
  model_id: string;
  provedor: string;
  ativo: boolean;
  em_cooldown: boolean;
}

export interface LogApi {
  timestamp: string;
  modelo: string;
  model_id: string;
  duracao_segundos: number;
  categoria: string;
  codigo_http: number | null;
  motivo: string;
  sugestao: string;
  erro_bruto: string;
}

export interface HistoricoMensagemApi {
  id: number;
  sessao_id: string;
  remetente: 'usuario' | 'agente';
  conteudo: string;
  modelo_utilizado: string | null;
  nivel_complexidade: string | null;
  motivo_complexidade: string | null; 
  fallback_acionado: number;
  duracao_segundos: number | null;
  timestamp: string;
}

export interface MetricasApi {
  total_requisicoes: number;
  tempo_medio_segundos: number;
  sucesso_por_provedor: Record<string, number>;
  falha_por_provedor: Record<string, number>;
}

// Evento SSE genérico — o backend manda `{tipo: string, ...dados}`.
// Os tipos mais relevantes para a UI:
//   'classificacao' | 'tentativa' | 'step_planejamento' | 'step_raciocinio'
//   | 'step_observacao' | 'step_erro' | 'falha' | 'retry' | 'sucesso'
//   | 'timeout_global' | 'erro_fatal' | 'final'
export type EventoStreaming = { tipo: string } & Record<string, any>;

async function requisitar<T>(caminho: string, opcoes?: RequestInit): Promise<T> {
  const resposta = await fetch(`${API_BASE}${caminho}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opcoes,
  });

  if (!resposta.ok) {
    let detalhe = resposta.statusText;
    try {
      const corpo = await resposta.json();
      detalhe = corpo.detail || detalhe;
    } catch {
      // corpo não era JSON, mantém o statusText
    }
    throw new Error(detalhe);
  }

  return resposta.json();
}

export const api = {
  enviarMensagem: (texto: string, sessaoId: string) =>
    requisitar<RespostaChatApi>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ texto, sessao_id: sessaoId }),
    }),

  listarProvedores: () => requisitar<ProvedorApi[]>('/api/provedores'),

  listarLogs: (limite = 50) => requisitar<LogApi[]>(`/api/logs?limite=${limite}`),

  limparLogs: () => requisitar<{ status: string }>('/api/logs', { method: 'DELETE' }),

  listarHistorico: (sessaoId: string, limite = 100) =>
    requisitar<HistoricoMensagemApi[]>(`/api/historico/${encodeURIComponent(sessaoId)}?limite=${limite}`),

  limparHistorico: (sessaoId: string) =>
    requisitar<{ status: string }>(
      `/api/historico/${encodeURIComponent(sessaoId)}`,
      { method: 'DELETE' },
    ),

  metricas: () => requisitar<MetricasApi>('/api/metricas'),

  healthCheck: () => requisitar<{ status: string }>('/health'),
};

/**
 * Consome /api/chat/stream via SSE (POST + ReadableStream, já que EventSource
 * só suporta GET). Chama `onEvento` a cada evento recebido e retorna o objeto
 * final consolidado (o mesmo que /api/chat retorna).
 */
export async function enviarMensagemStreaming(
  texto: string,
  sessaoId: string,
  onEvento: (evt: EventoStreaming) => void,
): Promise<RespostaChatApi> {
  const resposta = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ texto, sessao_id: sessaoId }),
  });

  if (!resposta.ok) {
    let detalhe = resposta.statusText;
    try {
      const corpo = await resposta.json();
      detalhe = corpo.detail || detalhe;
    } catch {
      // corpo não era JSON
    }
    throw new Error(detalhe);
  }

  if (!resposta.body) {
    throw new Error('Resposta do backend sem corpo — streaming não suportado?');
  }

  const reader = resposta.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let resultadoFinal: RespostaChatApi | null = null;
  let erroFatal: string | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE separa eventos por linha em branco (\n\n).
    const blocos = buffer.split('\n\n');
    buffer = blocos.pop() ?? '';
    for (const bloco of blocos) {
      const linha = bloco.replace(/^data:\s*/, '').trim();
      if (!linha) continue;
      let evt: EventoStreaming;
      try {
        evt = JSON.parse(linha);
      } catch {
        continue; // linha malformada, ignora
      }
      try {
        onEvento(evt);
      } catch {
        // erro no handler do consumidor não deve derrubar o stream
      }
      if (evt.tipo === 'final') {
        resultadoFinal = evt.resultado as RespostaChatApi;
      } else if (evt.tipo === 'erro_fatal') {
        erroFatal = evt.mensagem || 'Erro fatal desconhecido no backend.';
      }
    }
  }

  if (!resultadoFinal) {
    throw new Error(erroFatal || 'Streaming terminou sem resposta final.');
  }
  return resultadoFinal;
}