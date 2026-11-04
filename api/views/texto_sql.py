"""Endpoint admin de consulta em linguagem natural (Aula 21)."""

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from api.serializers import AskSQLRequestSerializer
from api.views.catalogo import IsAdminRole
from services import llm as llm_service
from services import texto_sql
from services.texto_sql.erros import TextoSqlErro


class AskSQLView(APIView):
    """Traduz a pergunta em SQL, executa e devolve SQL + resultado.

    É admin-only porque a consulta atravessa dados de todos os usuários e
    consome tokens pagos do provedor de LLM.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def post(self, request):
        serializer = AskSQLRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pergunta = serializer.validated_data["question"]

        try:
            resultado = texto_sql.responder(pergunta)
        except TextoSqlErro as exc:
            return Response(
                {"detail": str(exc), "erro": type(exc).__name__},
                status=exc.status_http,
            )
        except llm_service.LLMErro as exc:
            return Response(
                {"detail": str(exc), "erro": type(exc).__name__},
                status=exc.status_http,
            )
        return Response(resultado, status=200)
