# Rodando o backend como serviço systemd (opcional)

Isso é útil se você quiser que o backend fique rodando continuamente em um
servidor Linux, mesmo depois de fechar o terminal ou reiniciar a máquina.
Não é necessário para uso local no dia a dia — use `./start.sh` para isso.

1. Ajuste os caminhos abaixo para o local real do projeto e crie o arquivo
   `/etc/systemd/system/agente-resiliente.service`:

```ini
[Unit]
Description=Agente Resiliente LLM - Backend
After=network.target

[Service]
Type=simple
User=SEU_USUARIO
WorkingDirectory=/caminho/completo/para/agente_novo/backend
EnvironmentFile=/caminho/completo/para/agente_novo/backend/.env
ExecStart=/caminho/completo/para/agente_novo/backend/venv/bin/uvicorn app.api:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

2. Recarregue o systemd e habilite o serviço:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now agente-resiliente.service
```

3. Para ver logs do serviço:

```bash
sudo journalctl -u agente-resiliente.service -f
```

4. Para parar ou reiniciar:

```bash
sudo systemctl stop agente-resiliente.service
sudo systemctl restart agente-resiliente.service
```

O frontend (build de produção, `frontend/dist`) pode ser servido separadamente
por nginx ou outro servidor estático, apontando o proxy de `/api` para
`http://localhost:8000`.