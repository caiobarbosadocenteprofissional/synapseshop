from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from api.serializers import AssistRequestSerializer
from api.views.catalogo import IsAdminRole
from services import llm as llm_service


class AssistView(APIView):
    """Assistente de IA: sumariza ou explica logs (``POST /api/v1/assist``, Aula 14).

    A view é deliberadamente fina: valida o contrato de entrada e traduz o
    ``status_http`` de cada ``LLMErro`` em status da resposta. A resiliência
    (timeout, retry, circuit breaker), a redação de PII e a telemetria vivem em
    ``services.llm`` — a API não deveria saber *como* se sobrevive a uma queda do
    provedor, só que a camada de IA sabe.

    Requer autenticação: o assistente consome tokens pagos e recebe logs internos,
    então não é um endpoint anónimo.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = AssistRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data

        try:
            resultado = llm_service.assistir(
                mode=dados["mode"],
                logs=dados["logs"],
                temperature=dados["temperature"],
                max_tokens=dados["max_tokens"],
            )
        except llm_service.LLMErro as exc:
            return Response(
                {"detail": str(exc), "erro": type(exc).__name__},
                status=exc.status_http,
            )
        return Response(resultado, status=200)


class AssistStatsView(APIView):
    """Métricas do ``llm_service`` (Aula 14), restritas ao papel admin.

    ``GET`` devolve latência média, taxa de erro, consumo de tokens, custo
    estimado e o estado do circuito. ``POST`` zera os contadores e fecha o
    circuito, abrindo uma nova janela de medição — é o análogo de
    ``/api/v1/cache/stats/`` para a camada de IA.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request):
        return Response(llm_service.metricas())

    def post(self, request):
        llm_service.resetar_metricas()
        llm_service.redefinir_circuito()
        return Response(llm_service.metricas())
