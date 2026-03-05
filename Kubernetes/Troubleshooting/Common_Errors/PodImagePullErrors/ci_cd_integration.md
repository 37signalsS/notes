# Pod Image Pull Errors: Интеграция с CI/CD

## Интеграция с CI/CD

### GitLab CI/CD

```yaml
# .gitlab-ci.yml
deploy:
  stage: deploy
  image: bitnami/kubectl
  script:
  - kubectl create secret docker-registry regcred \
    --docker-server=$CI_REGISTRY \
    --docker-username=$CI_REGISTRY_USER \
    --docker-password=$CI_REGISTRY_PASSWORD \
    --namespace=$KUBE_NAMESPACE \
    --dry-run=client -o yaml | kubectl apply -f -
  - kubectl patch serviceaccount default -p '{"imagePullSecrets": [{"name": "regcred"}]}' -n $KUBE_NAMESPACE
```

> **См. также:** [`../../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md`](../../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)

### ArgoCD

ArgoCD автоматически использует `imagePullSecrets`, указанные в манифесте. Убедитесь, что secret создан в том же namespace, где развертывается приложение.
