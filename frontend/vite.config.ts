import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig } from 'vite';

// Configuração do Vite para o frontend do Agente Resiliente.
//
// Para um dev júnior:
// - `server.proxy` redireciona chamadas de /api/* feitas pelo frontend
//   (ex: fetch('/api/chat')) para o backend Python (FastAPI) rodando em
//   outra porta. Isso evita problemas de CORS durante o desenvolvimento.
// - Se você mudar a porta do backend (ver backend/app/api.py / start.sh),
//   atualize o `target` abaixo.
export default defineConfig(() => {
  const backendUrl = process.env.VITE_BACKEND_URL || 'http://localhost:8000';

  // O Vite bloqueia por padrão requisições vindas de hosts desconhecidos
  // (proteção contra DNS rebinding). Isso barra o acesso via túnel
  // (Cloudflare/ngrok) mesmo com tudo configurado corretamente — o sintoma é
  // a tela "Blocked request. This host (...) is not allowed.".
  //
  // Para liberar, defina no frontend/.env a variável VITE_ALLOWED_HOST com o
  // domínio do túnel do FRONTEND (o mesmo que a pessoa vai abrir no navegador),
  // sem "https://" na frente. Exemplo:
  //   VITE_ALLOWED_HOST=sua-url-de-tunel-do-frontend.trycloudflare.com
  // Assim como VITE_API_BASE_URL, é preciso reiniciar `./start.sh --gui` depois
  // de mudar essa variável.
  const hostPermitidoExtra = process.env.VITE_ALLOWED_HOST;

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      port: 3000,
      // Trava a porta em 3000: se já estiver ocupada, o Vite falha com um erro
      // claro em vez de "escapar" silenciosamente para outra porta (3001, 3002...).
      // Isso importa especialmente ao expor via túnel (Cloudflare/ngrok), onde o
      // túnel aponta para uma porta fixa — se o Vite mudasse de porta sozinho, o
      // túnel ficaria apontando para o lugar errado sem nenhum aviso.
      strictPort: true,
      host: '0.0.0.0',
      allowedHosts: hostPermitidoExtra ? [hostPermitidoExtra] : ['ship-telephone-assessment-southwest.trycloudflare.com'],
      proxy: {
        '/api': {
          target: backendUrl,
          changeOrigin: true,
        },
      },
    },
  };
});