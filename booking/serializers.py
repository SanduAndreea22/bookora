from rest_framework import serializers

from .models import Review, Service, Workspace


class ServiceSerializer(serializers.ModelSerializer):
    formatted_price = serializers.ReadOnlyField()

    class Meta:
        model = Service
        fields = ["id", "name", "description", "duration_min", "price", "formatted_price"]


class ReviewSerializer(serializers.ModelSerializer):
    customer = serializers.ReadOnlyField(source="customer.username")

    class Meta:
        model = Review
        fields = ["id", "customer", "rating", "comment", "created_at"]


class WorkspaceListSerializer(serializers.ModelSerializer):
    rating_average = serializers.FloatField(read_only=True)
    rating_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Workspace
        fields = ["id", "name", "slug", "city", "address", "currency", "rating_average", "rating_count"]


class WorkspaceDetailSerializer(WorkspaceListSerializer):
    services = serializers.SerializerMethodField()

    class Meta(WorkspaceListSerializer.Meta):
        fields = WorkspaceListSerializer.Meta.fields + ["services"]

    def get_services(self, obj):
        active_services = obj.services.filter(is_active=True).order_by("name")
        return ServiceSerializer(active_services, many=True).data
