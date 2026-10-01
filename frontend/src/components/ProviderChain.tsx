import React from 'react';
import { ProvedorLLM } from '../types';
import { Server, Clock } from 'lucide-react';

interface ProviderChainProps {
  provedores: ProvedorLLM[];
  provedorExecutandoNome?: string | null;
  carregando?: boolean;
  erro?: string | null;
}

// Nomes de exibição e cores por provedor_id cru (o backend manda o id técnico,
// ex: "google", "groq", "ollama" — aqui só cuidamos da apresentação visual).
const ESTILO_POR_PROVEDOR: Record<string, { label: string; classe: string }> = {
  google: { label: 'Google', classe: 'text-sky-400 bg-sky-950/60 border-sky-800/60' },
  groq: { label: 'Groq', classe: 'text-orange-400 bg-orange-950/60 border-orange-800/60' },
  openrouter: { label: 'OpenRouter', classe: 'text-purple-400 bg-purple-950/60 border-purple-800/60' },
  github: { label: 'GitHub Models', classe: 'text-slate-300 bg-slate-800/60 border-slate-700/60' },
  cloudflare: { label: 'Cloudflare', classe: 'text-amber-400 bg-amber-950/60 border-amber-800/60' },
  mistral: { label: 'Mistral', classe: 'text-red-400 bg-red-950/60 border-red-800/60' },
  cerebras: { label: 'Cerebras', classe: 'text-cyan-400 bg-cyan-950/60 border-cyan-800/60' },
  cohere: { label: 'Cohere', classe: 'text-pink-400 bg-pink-950/60 border-pink-800/60' },
  sambanova: { label: 'SambaNova', classe: 'text-yellow-400 bg-yellow-950/60 border-yellow-800/60' },
  huggingface: { label: 'Hugging Face', classe: 'text-fuchsia-400 bg-fuchsia-950/60 border-fuchsia-800/60' },
  ollama: { label: 'Local', classe: 'text-emerald-400 bg-emerald-950/60 border-emerald-800/60' },
};

function estiloDoProvedor(provedorId: string) {
  return ESTILO_POR_PROVEDOR[provedorId] ?? { label: provedorId, classe: 'text-slate-400 bg-slate-800/60 border-slate-700/60' };
}

// Mostra a esteira real de provedores configurados no backend (via GET /api/provedores).
// A ordem de tentativa não é mais fixa: ela é recalculada a cada mensagem pelo
// TaskComplexityRouter + FallbackChain do backend, com base na complexidade do
// pedido e em quais provedores estão em cooldown (após um 429 recente). Este
// componente só exibe o inventário de provedores configurados e seu estado atual.
export const ProviderChain: React.FC<ProviderChainProps> = ({
  provedores,
  provedorExecutandoNome,
  carregando,
  erro,
}) => {
  return (
    <div id="pipeline-fallback-container" className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4 pb-3 border-b border-slate-800">
        <div>
          <h2 className="text-base font-semibold text-slate-100 flex items-center gap-2">
            <Server className="w-4 h-4 text-emerald-400" />
            Provedores Configurados (Multi-LLM)
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            A cada mensagem, o backend escolhe o provedor mais adequado à complexidade da
            tarefa; o modelo local (Ollama) só entra se todos os demais falharem.
          </p>
        </div>
      </div>

      {erro && (
        <div className="text-xs text-rose-300 bg-rose-950/40 border border-rose-800/60 rounded-lg p-3">
          Não foi possível carregar os provedores do backend: {erro}
        </div>
      )}

      {carregando && !erro && (
        <div className="text-xs text-slate-500">Carregando provedores configurados no backend...</div>
      )}

      {!carregando && !erro && provedores.length === 0 && (
        <div className="text-xs text-slate-500">
          Nenhum provedor configurado ainda. Defina ao menos uma chave de API (ex:
          GEMINI_API_KEY, GROQ_API_KEY) e/ou habilite OLLAMA_ENABLED no .env do backend.
        </div>
      )}

      {!carregando && !erro && provedores.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
          {provedores.map((prov) => {
            const isExecutando = provedorExecutandoNome === prov.nome;
            const estilo = estiloDoProvedor(prov.provedor);

            return (
              <div
                key={prov.id}
                id={`card-provedor-${prov.id}`}
                className={`relative rounded-lg p-3.5 border transition-all duration-200 ${
                  isExecutando
                    ? 'border-indigo-500 bg-indigo-950/40 ring-2 ring-indigo-500/20'
                    : prov.em_cooldown
                    ? 'border-amber-800/60 bg-amber-950/10'
                    : 'border-slate-800 bg-slate-800/60 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className={`text-[10px] font-medium px-1.5 py-0.2 rounded border ${estilo.classe}`}>
                    {estilo.label}
                  </span>
                </div>

                <div className="text-sm font-semibold text-slate-200 truncate" title={prov.nome}>
                  {prov.nome}
                </div>
                {prov.model_id && (
                  <div className="text-[11px] font-mono text-slate-400 truncate" title={prov.model_id}>
                    {prov.model_id}
                  </div>
                )}

                {prov.em_cooldown ? (
                  <div className="mt-2 flex items-center gap-1 text-[10px] text-amber-400 font-medium">
                    <Clock className="w-3 h-3" />
                    Em cooldown (rate-limit recente)
                  </div>
                ) : (
                  <div className="mt-2 flex items-center gap-1 text-[10px] text-emerald-400 font-medium">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                    Disponível
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};