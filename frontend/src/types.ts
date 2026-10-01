// Tipos usados pelo frontend. Estes espelham o que a API real (backend/app/api.py)
// devolve — se você mudar o formato de resposta no backend, atualize aqui também.

export interface ProvedorLLM {
  id: string;
  nome: string;
  model_id: string;
  provedor: string; // id cru do provedor: "google", "groq", "openrouter", "ollama", etc.
  ativo: boolean;
  em_cooldown: boolean;
}

export interface DiagnosticoFalha {
  id: string;
  timestamp: string;
  modeloNome: string;
  modelId: string;
  codigoHttp: number | null;
  categoria: string;
  motivoAmigavel: string;
  sugestao: string;
  detalhesBrutos: string;
  proximoModelo: string | null;
  duracaoSegundos: number;
}

export interface MensagemChat {
  id: string;
  remetente: 'usuario' | 'agente';
  conteudo: string;
  timestamp: string;
  modeloUtilizado?: string;
  fallbackAcionado?: boolean;
  modelosFalhados?: {
    nome: string;
    categoria: string;
    codigoHttp: number | null;
  }[];
  duracaoSegundos?: number;
  nivelComplexidade?: string;
  motivoComplexidade?: string; 
  sucesso?: boolean;
}