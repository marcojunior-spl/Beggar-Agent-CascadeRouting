import React, { useState } from 'react';
import { DiagnosticoFalha } from '../types';
import { AlertCircle, Clock, ShieldCheck, Trash2, Filter, Info, Terminal } from 'lucide-react';

interface DiagnosticLogsProps {
  logs: DiagnosticoFalha[];
  onLimparLogs: () => void;
}

export const DiagnosticLogs: React.FC<DiagnosticLogsProps> = ({ logs, onLimparLogs }) => {
  const [filtroCodigo, setFiltroCodigo] = useState<string>('todos');

  const logsFiltrados = logs.filter((log) => {
    if (filtroCodigo === 'todos') return true;
    if (filtroCodigo === '404') return log.codigoHttp === 404;
    if (filtroCodigo === '429') return log.codigoHttp === 429;
    if (filtroCodigo === '401') return log.codigoHttp === 401 || log.codigoHttp === 403;
    if (filtroCodigo === '500') return log.codigoHttp && log.codigoHttp >= 500;
    return true;
  });

  const getBadgeColor = (codigo: number | null) => {
    switch (codigo) {
      case 404:
        return 'bg-rose-950/80 text-rose-300 border-rose-800/80';
      case 429:
        return 'bg-amber-950/80 text-amber-300 border-amber-800/80';
      case 401:
      case 403:
        return 'bg-yellow-950/80 text-yellow-300 border-yellow-800/80';
      case 500:
      case 502:
      case 503:
        return 'bg-purple-950/80 text-purple-300 border-purple-800/80';
      default:
        return 'bg-slate-800 text-slate-300 border-slate-700';
    }
  };

  return (
    <div id="painel-diagnostico-logs" className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4 pb-3 border-b border-slate-800">
        <div>
          <h2 className="text-base font-semibold text-slate-100 flex items-center gap-2">
            <Terminal className="w-4 h-4 text-rose-400" />
            Registro de Falhas & Diagnóstico Específico
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Logs estruturados com categoria, código de status HTTP, diagnóstico da falha e ação corretiva adotada.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Filtro de Códigos */}
          <div className="flex items-center gap-1.5 text-xs">
            <Filter className="w-3.5 h-3.5 text-slate-400" />
            <select
              id="filtro-codigo-erro"
              value={filtroCodigo}
              onChange={(e) => setFiltroCodigo(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-200 text-xs focus:outline-none"
            >
              <option value="todos">Todos os Erros ({logs.length})</option>
              <option value="404">HTTP 404 (Model Not Found)</option>
              <option value="429">HTTP 429 (Rate Limit / Quota)</option>
              <option value="401">HTTP 401/403 (Auth / Chave)</option>
              <option value="500">HTTP 5xx (Servidor)</option>
            </select>
          </div>

          {logs.length > 0 && (
            <button
              id="btn-limpar-logs"
              onClick={onLimparLogs}
              className="flex items-center gap-1 px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200 bg-slate-800/80 hover:bg-slate-800 border border-slate-700 rounded transition-colors"
              title="Limpar histórico de logs"
            >
              <Trash2 className="w-3 h-3" />
              Limpar
            </button>
          )}
        </div>
      </div>

      {logsFiltrados.length === 0 ? (
        <div className="text-center py-8 text-slate-500 text-xs">
          <ShieldCheck className="w-8 h-8 text-emerald-500/50 mx-auto mb-2" />
          Nenhum registro de falha encontrado no momento. Os provedores estão respondendo normalmente.
        </div>
      ) : (
        <div className="space-y-3 max-h-[420px] overflow-y-auto pr-1">
          {logsFiltrados.map((log) => (
            <div
              key={log.id}
              id={`log-item-${log.id}`}
              className="bg-slate-950/70 border border-slate-800/90 rounded-lg p-3.5 text-xs hover:border-slate-700 transition-colors"
            >
              <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`font-mono text-[11px] font-bold px-2 py-0.5 rounded border ${getBadgeColor(
                      log.codigoHttp
                    )}`}
                  >
                    {log.codigoHttp ? `HTTP ${log.codigoHttp}` : 'ERRO'}
                  </span>
                  <span className="font-semibold text-slate-200">{log.modeloNome}</span>
                  <span className="text-[11px] font-mono text-slate-500">({log.modelId})</span>
                </div>

                <div className="flex items-center gap-2 text-slate-400 text-[11px]">
                  <span className="flex items-center gap-1 font-mono">
                    <Clock className="w-3 h-3" />
                    {log.timestamp}
                  </span>
                  <span className="text-slate-600">|</span>
                  <span>{log.duracaoSegundos}s</span>
                </div>
              </div>

              {/* Diagnóstico Amigável */}
              <div className="bg-slate-900/90 rounded p-2.5 mb-2 border border-slate-800/80">
                <div className="flex items-start gap-2 text-slate-300">
                  <AlertCircle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <div className="font-medium text-slate-200 mb-0.5">{log.categoria}</div>
                    <p className="text-slate-400 leading-relaxed">{log.motivoAmigavel}</p>
                  </div>
                </div>
              </div>

              {/* Sugestão de Resolução e Próximo Modelo */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px]">
                <div className="bg-emerald-950/20 border border-emerald-900/40 rounded px-2.5 py-1.5 text-emerald-300/90">
                  <span className="font-semibold text-emerald-400">💡 Sugestão Técnica: </span>
                  {log.sugestao}
                </div>
                <div className="bg-indigo-950/20 border border-indigo-900/40 rounded px-2.5 py-1.5 text-indigo-300/90">
                  <span className="font-semibold text-indigo-400">🔄 Ação de Fallback: </span>
                  {log.proximoModelo
                    ? `Alternado automaticamente para ${log.proximoModelo}`
                    : 'Tentando próximo provedor na fila'}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};