from rest_framework.routers import DefaultRouter

from . import api

router = DefaultRouter()
router.register("workspaces", api.WorkspaceViewSet, basename="workspace")

urlpatterns = router.urls
