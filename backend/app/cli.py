"""
Modo terminal (CLI) do Agente Resiliente.

Uso:
    python -m app.cli

Este modo não depende do frontend nem do servidor web — é uma conversa
direta no terminal, útil para testes rápidos, debug, ou uso em servidores
sem interface gráfica.
"""

from dotenv import load_dotenv

load_dotenv()

from .agente import AssistenteDesenvolvimento


def main():
    try:
        assistente = AssistenteDesenvolvimento()
    except RuntimeError as e:
        print(f"\n❌ Não foi possível iniciar o agente: {e}\n")
        return

    print("\n" + "━" * 60)
    print("🤖 Agente Resiliente Híbrido (Multi-Provedor + Fallback Local)")
    total_provedores = len(assistente.registry.listar_todos())
    tem_ollama = assistente.registry.tem_ollama()
    print(f"📋 Provedores em nuvem configurados: {total_provedores}"
          f"{' + modelo local (Ollama) como fallback extremo' if tem_ollama else ''}")
    print("━" * 60)

    while True:
        try:
            prompt = input("\nVocê: ").strip()
            if not prompt:
                continue
            if prompt.lower() in ["sair", "exit", "quit"]:
                print("\nEncerrando sessão com segurança. Até logo!")
                break

            resultado = assistente.executar_com_fallback(
                prompt,
                on_evento=_imprimir_evento,
            )
            print(f"\nAgente: {resultado['resposta']}")

        except KeyboardInterrupt:
            print("\n\nInterrupção detectada. Encerrando sessão...")
            break


def _imprimir_evento(evento: dict):
    tipo = evento.get("tipo")
    if tipo == "classificacao":
        print(f"\n🧭 Complexidade detectada: {evento['nivel'].upper()} — {evento['motivo']}")
    elif tipo == "tentativa":
        marca = "🏠 [Local]" if evento.get("eh_local") else ("🔄 [Fallback]" if evento["eh_fallback"] else "🚀")
        print(f"\n{marca} Tentando: {evento['modelo']} ({evento['indice'] + 1}/{evento['total']})...")
    elif tipo == "retry":
        print(f"\n⏳ {evento['modelo']} — erro temporário, tentando de novo em {evento['espera_segundos']}s "
              f"(tentativa {evento['tentativa']})...")
    elif tipo == "falha":
        log = evento["log"]
        print(f"\n⚠️  {log['modelo']} falhou — {log['categoria']}")
        print(f"    Diagnóstico: {log['motivo']}")
        print(f"    Sugestão: {log['sugestao']}")
    elif tipo == "sucesso":
        print(f"\n✅ Resposta gerada por '{evento['modelo']}' ({evento['duracao']}s).")
    elif tipo == "erro_fatal":
        print(f"\n❌ {evento['mensagem']}")


if __name__ == "__main__":
    main()