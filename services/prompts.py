"""Templates de prompt do assistente (Aula 14).

Um prompt é uma decisão de produto, não um detalhe de implementação: o texto do
sistema define o comportamento observável do assistente (idioma, formato,
limite de especulação) e é o artefato que a equipe revisa quando a resposta sai
errada. Por isso ele mora em um módulo próprio, versionado, e não embutido na
chamada HTTP.

Dois modos, porque as perguntas são diferentes:

- ``summarize`` — "o que aconteceu?" — reduz um volume de logs ao essencial;
- ``explain`` — "por que aconteceu e o que fazer?" — interpreta os logs e aponta
  a causa provável e o próximo passo.

Ambos recebem **logs já redigidos** (ver ``services.llm.redigir``): o prompt é o
último ponto antes do dado sair da nossa infraestrutura, e é aqui que a política
de privacidade tem de estar garantida — não no provedor.
"""

from typing import Iterable, List, Union

MODO_SUMARIZAR = "summarize"
MODO_EXPLICAR = "explain"

#: Modos aceites pelo endpoint, na mesma ordem dos ``choices`` do serializer.
MODOS = (MODO_SUMARIZAR, MODO_EXPLICAR)

_CONTRATO_COMUM = (
    "Você é o assistente de suporte do SynapseShop, um backend de pedidos. "
    "Responda em português do Brasil. Baseie-se exclusivamente nos logs "
    "fornecidos: se a causa não puder ser concluída a partir deles, diga "
    "explicitamente o que falta em vez de especular. Nunca revele dados pessoais."
)

#: Prompt de sistema por modo. O texto é o template revisável pela equipe.
PROMPTS_SISTEMA = {
    MODO_SUMARIZAR: (
        f"{_CONTRATO_COMUM} "
        "Sua tarefa é SUMARIZAR os logs em até 5 tópicos objetivos. "
        "Cada tópico deve citar o evento e a contagem de ocorrências quando "
        "isso estiver evidente nos logs. Não proponha correções nesta modalidade."
    ),
    MODO_EXPLICAR: (
        f"{_CONTRATO_COMUM} "
        "Sua tarefa é EXPLICAR os logs: descreva o que eles mostram, a causa "
        "provável e o próximo passo de diagnóstico. Separe a resposta em "
        "'O que ocorreu', 'Causa provável' e 'Próximo passo'."
    ),
}


def normalizar_logs(logs: Union[str, Iterable[str]]) -> str:
    """Achata a entrada (`str` ou lista de linhas) numa única string.

    O contrato aceita uma string única ou um array — logs colados do terminal
    costumam ser uma string, logs vindos de um coletor costumam ser array. A
    normalização acontece antes da redação, para que a política seja aplicada uma
    só vez sobre o texto final.
    """
    if isinstance(logs, str):
        return logs
    return "\n".join(str(linha) for linha in logs)


def montar_mensagens(mode: str, logs: str) -> List[dict]:
    """Monta a lista de mensagens no formato Chat Completions.

    ``mode`` deve já ter sido validado pelo serializer (``summarize``/``explain``);
    um modo desconhecido aqui é erro de programação, não de entrada do usuário.
    """
    return [
        {"role": "system", "content": PROMPTS_SISTEMA[mode]},
        {"role": "user", "content": f"Logs:\n{logs}"},
    ]
