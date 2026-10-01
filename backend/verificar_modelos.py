#!/usr/bin/env python3
"""
Verificador de modelos do catálogo.

Uso (de dentro de backend/, com o venv ativo):
    python verificar_modelos.py

Faz uma chamada mínima a cada modelo configurado no catálogo. Reporta quais
estão vivos, quais deram erro, e qual foi o erro.

Usa litellm.completion() diretamente (NÃO passa pelo smolagents.LiteLLMModel)
porque o wrapper do smolagents faz transformações adicionais que podem
obscurecer o erro real da API — o objetivo aqui é ver o que a API devolve.
"""

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import litellm

from app.providers.catalogo import MODELOS_CATALOGADOS, obter_definicao

# Silencia logs verbosos do litellm para o output ficar legível
litellm.suppress_debug_info = True


def testar_modelo(modelo) -> dict:
    """Faz uma chamada mínima ao modelo e retorna resultado + erro se houver."""
    definicao = obter_definicao(modelo.provedor_id)
    if not definicao:
        return {"status": "skip", "erro": f"Definição de provedor não encontrada: {modelo.provedor_id}"}

    api_key = os.environ.get(definicao.env_api_key)
    if not api_key:
        return {"status": "skip", "erro": f"Chave {definicao.env_api_key} não configurada"}

    # Seta as env vars que o LiteLLM espera. Ele lê direto do ambiente, então
    # é mais simples setar aqui do que passar tudo via parâmetro.
    os.environ[definicao.env_api_key] = api_key
    for var in definicao.env_extra:
        valor = os.environ.get(var)
        if not valor:
            return {"status": "skip", "erro": f"Env var faltando: {var}"}

    try:
        t0 = time.time()
        resposta = litellm.completion(
            model=modelo.model_id_template,
            messages=[{"role": "user", "content": "Responda apenas: ok"}],
            max_tokens=10,
        )
        duracao = round(time.time() - t0, 2)

        # Extrai o texto de forma defensiva (diferentes providers devolvem
        # estruturas ligeiramente diferentes).
        try:
            texto = resposta.choices[0].message.content or ""
        except (AttributeError, IndexError, KeyError, TypeError):
            texto = str(resposta)[:60]

        return {"status": "ok", "resposta": str(texto)[:60], "duracao": duracao}

    except Exception as e:
        msg = str(e)
        if len(msg) > 200:
            msg = msg[:200] + "..."
        return {"status": "erro", "erro": msg, "tipo": type(e).__name__}


def main():
    total = len(MODELOS_CATALOGADOS)
    print(f"\n{'=' * 70}")
    print(f"Verificando {total} modelos do catálogo (um por vez)...")
    print(f"{'=' * 70}\n")

    vivos = 0
    falhados = 0
    pulados = 0

    for i, modelo in enumerate(MODELOS_CATALOGADOS, 1):
        print(f"[{i:2d}/{total}] {modelo.provedor_id:12s} | {modelo.nome_exibicao}...", end=" ", flush=True)

        resultado = testar_modelo(modelo)

        if resultado["status"] == "ok":
            vivos += 1
            print(f"✅ OK ({resultado['duracao']}s)")
        elif resultado["status"] == "skip":
            pulados += 1
            print(f"⏭️  SKIP ({resultado['erro']})")
        else:
            falhados += 1
            print(f"❌ {resultado['tipo']}")
            print(f"      {resultado['erro']}")

    print(f"\n{'=' * 70}")
    print(f"RESUMO: {vivos} vivos | {falhados} com erro | {pulados} pulados")
    print(f"{'=' * 70}\n")

    if falhados > 0:
        print("Modelos com erro provavelmente foram descontinuados ou renomeados.")
        print("Atualize-os em backend/app/providers/catalogo.py.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()