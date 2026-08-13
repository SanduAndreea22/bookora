from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError
from rest_framework.response import Response

from .models import Service, Workspace
from .serializers import ReviewSerializer, WorkspaceDetailSerializer, WorkspaceListSerializer
from .services import get_available_slots


def _with_rating_stats(queryset):
    return queryset.annotate(rating_average=Avg("reviews__rating"), rating_count=Count("reviews"))


class WorkspaceViewSet(viewsets.ReadOnlyModelViewSet):
    """Public, read-only access to businesses on the marketplace."""

    queryset = _with_rating_stats(Workspace.objects.all()).order_by("name")
    lookup_field = "slug"
    permission_classes = [permissions.AllowAny]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return WorkspaceDetailSerializer
        return WorkspaceListSerializer

    @action(detail=True, methods=["get"])
    def reviews(self, request, slug=None):
        workspace = self.get_object()
        qs = workspace.reviews.select_related("customer").order_by("-created_at")
        page = self.paginate_queryset(qs)
        serializer = ReviewSerializer(page if page is not None else qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def slots(self, request, slug=None):
        workspace = self.get_object()
        service_id = request.query_params.get("service")
        day_str = request.query_params.get("date")

        if not service_id or not day_str:
            raise ParseError("Query params 'service' and 'date' (YYYY-MM-DD) are required.")

        service = get_object_or_404(Service, id=service_id, workspace=workspace)
        day = parse_date(day_str)
        if not day:
            raise ParseError("Invalid 'date' format, expected YYYY-MM-DD.")

        slots = get_available_slots(workspace=workspace, service=service, day=day)
        return Response({"slots": [s.isoformat() for s in slots]})
