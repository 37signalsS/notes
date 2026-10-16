# Список файлов с практическим применением FluxCD

> Файлы **вне директории GitOps/**, содержащие реальные манифесты FluxCD (CRD: `GitRepository`, `Kustomization`, `HelmRelease`, `ImageRepository`, `ImagePolicy`, `ImageUpdateAutomation`, `OCIRepository`, `Receiver`, `Provider`, `Alert`, `image.toolkit.fluxcd.io`), команды `flux CLI`, настройки и сценарии для развертывания конкретных инструментов.

---

## Мониторинг и Observability

| № | Файл | Технология | Что содержит по FluxCD |
|---|------|-----------|----------------------|
| 1 | Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/argocd_installation.md | kube-prometheus-stack | `HelmRepository` + `HelmRelease` для установки стека | **ГОТОВО** (конвертировано в Argo CD: `Application` + `repoURL`/Secret + `argocd app sync`) |
| 2 | Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/application_exporters_argocd.md | Экспортеры (Node, Kafka, Redis, PostgreSQL, Blackbox) | `HelmRelease` + `GitRepository` для экспортеров, `flux get/reconcile` команды | **ГОТОВО** (конвертировано в Argo CD: `Application` с `repoURL`/`Secret` + `argocd app sync/get`) |
| 3 | Prometheus/kubernetes/operator/gitops_integration.md | Prometheus Operator | `Kustomization` для развёртывания CRD и контроллера | **ГОТОВО** (удалён Flux-раздел `Kustomization`, оставлен Argo CD `Application`; `flux-system` → `argocd` namespace) |
| 4 | Prometheus/Exporters/blackbox/blackbox_exporter_installation_and_setup.md | Blackbox Exporter | `HelmRelease` + `Kustomization` для Blackbox | **ГОТОВО** (Flux `HelmRelease` → Argo CD `Application`, `dependsOn` → Sync Waves) |
| 5 | Loki/loki_stack_setup/loki_installation.md | Loki | `HelmRelease` для Loki (Сценарий 2.1), `flux get hr` | **ГОТОВО** (Flux `HelmRelease` → Argo CD `Application`, `flux get hr` → `argocd app get`) |
| 6 | Kubernetes/MonitoringLogging/EFK/efk_gitops.md | EFK (Elasticsearch/Fluentd/Kibana) | `GitRepository` + `Kustomization` для EFK стека | **ГОТОВО** (удалена Flux `Kustomization`/`GitRepository`; оставлен Argo CD `Application` + `AppProject`) |
| 7 | OpenTelemetry/gitops_collector.md | OpenTelemetry Collector | `GitRepository` + `HelmRelease` + `Kustomization` для Collector | **ГОТОВО** (Flux `HelmRelease` → Argo CD `Application`, удалена Flux `HelmRepository`) |

## Базы данных

| № | Файл | Технология | Что содержит по FluxCD |
|---|------|-----------|----------------------|
| 8 | Databases/PostgreSQL/Operations/kubernetes_deployment.md | PostgreSQL / CloudNativePG | `HelmRelease` для cloudnative-pg | **ГОТОВО** (Flux `HelmRelease` → Argo CD `Application`) |

## Брокеры сообщений

| № | Файл | Технология | Что содержит по FluxCD |
|---|------|-----------|----------------------|
| 9 | Kafka/kafka_bitnami_helm_chart.md | Kafka | `HelmRelease` для Kafka с `GitRepository` source | **ГОТОВО** (Flux `HelmRelease` → Argo CD `Application` с OCI source + `valueFiles` через `$values`) |

## Сеть и шлюзы

| № | Файл | Технология | Что содержит по FluxCD |
|---|------|-----------|----------------------|
| 10 | WebServers/Traefik/traefik-gitops.md | Traefik | `GitRepository` + `HelmRelease` для Traefik, `flux trigger receiver` | **ГОТОВО** (Flux `HelmRelease` → Argo CD `Application` с Helm chart; удалены Flux-команды и ссылки) |
| 11 | Kubernetes/Networking/gateway_api/gitops_cicd.md | Gateway API | `Kustomization` + `GitRepository` для Gateway API | **ГОТОВО** (Flux `Kustomization` + `GitRepository` + diagnostics удалены; RBAC/monitoring упоминания заменены на Argo CD) |

## Безопасность

| № | Файл | Технология | Что содержит по FluxCD |
|---|------|-----------|----------------------|
| 12 | Kubernetes/Security/trivy_operator.md | Trivy Operator | `HelmRelease` для trivy-operator |
| 13 | Kubernetes/Security/sealed_secrets_overview.md | Sealed Secrets | `HelmRelease` для Sealed Secrets (hub-and-spoke), `flux-system` namespace |
| 14 | Kubernetes/Base/secrets/external_managers.md | External Secrets Operator | `HelmRelease` для ESO через Flux CD |
| 15 | Kubernetes/Security/rbac/gitops_rbac_patterns.md | RBAC для FluxCD | `apiGroups: ["helm.toolkit.fluxcd.io"]`, ServiceAccount impersonation |

## CI/CD и приложения

| № | Файл | Технология | Что содержит по FluxCD |
|---|------|-----------|----------------------|
| 16 | CI-CD/Frontend_CI_CD/frontend_gitops.md | Frontend | `ImageRepository`, `ImagePolicy`, `ImageUpdateAutomation`, `GitRepository` + `HelmRelease` |
| 17 | CI-CD/GitLab_CI/Tutorials/sonarqube_integration.md | SonarQube | `HelmRelease` для SonarQube через Flux |
| 18 | CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md | GitLab + Flux | `flux bootstrap gitlab` для интеграции |

## Deployment / Operations

| № | Файл | Технология | Что содержит по FluxCD |
|---|------|-----------|----------------------|
| 19 | Kubernetes/Base/Deployment/deployment_with_gitops.md | Deployment | `Kustomization` для Deployment через Flux, `flux get/reconcile` |
| 20 | Kubernetes/Base/Deployment/advanced_rollback_strategies.md | Rollback | `flux reconcile/suspend/resume kustomization` для Break-Glass |

## Конфигурация и операции

| № | Файл | Технология | Что содержит по FluxCD |
|---|------|-----------|----------------------|
| 21 | Kubernetes/Base/ConfigMap/immutable.md | ConfigMap | Настройка `prune: true` в `Kustomization` для очистки |
| 22 | Kubernetes/Autoscaling/gitops_autoscaling.md | HPA/VPA/KEDA | `Kustomization` с `spec.ignore` для разрешения конфликтов с HPA |

## Инструменты Kubernetes

| № | Файл | Технология | Что содержит по FluxCD |
|---|------|-----------|----------------------|
| 23 | Kubernetes/ToolsUtilities/cert_manager/Administration/gitops_integration.md | cert-manager | `Kustomization` с аннотациями `prune: disabled` для CRD |
| 24 | Kubernetes/ToolsUtilities/reloader/reloader_installation.md | Reloader | `Kustomization` для установки Reloader через Flux |
| 25 | Kubernetes/ToolsUtilities/reloader/reloader_usage_scenarios.md | Reloader | `Kustomization` для сценариев использования |
| 26 | Kubernetes/ToolsUtilities/reloader/reloader_monitoring_and_best_practices.md | Reloader | `Kustomization` с health checks и настройками |
| 27 | Kubernetes/ToolsUtilities/vcluster/vcluster_gitops_integration.md | vcluster | `GitRepository` + `Kustomization` для vcluster |
| 28 | Kubernetes/ToolsUtilities/kustomize/kustomize_cd_integration.md | Kustomize | `GitRepository` + `Kustomization` для CD-пайплайнов |
| 29 | Kubernetes/ToolsUtilities/kustomize/kustomize_multi_cluster.md | Kustomize | `Kustomization` для multi-cluster |
| 30 | Kubernetes/ToolsUtilities/kustomize/kustomize_debugging.md | Kustomize debugging | `flux get kustomization`, `flux logs`, `flux reconcile` |
| 31 | Kubernetes/ToolsUtilities/lens/practical_scenarios.md | Lens (UI) | Интеграция Lens с Flux CD (навигация по ресурсам, `@fluxcd/lens-extension`) |

## Инфраструктура

| № | Файл | Технология | Что содержит по FluxCD |
|---|------|-----------|----------------------|
| 32 | Docker/Docker_registries/Harbor/replication.md | Harbor | `ImageRepository` для управления образами через FluxCD |

---

## Исключённые (поверхностные упоминания, без практических манифестов/команд)

| Файл | Почему исключён |
|------|----------------|
| Kubernetes/kustomize.md | Теоретическое упоминание `HelmRelease` как концепции |
| Kubernetes/ToolsUtilities/kustomize/kustomize_generators.md | Теоретическое упоминание `HelmRelease` для `valuesFrom` |
| Kubernetes/Security/rbac/aggregation_scenarios.md | `kind: Kustomization` относится к Kustomize (`kustomize.config.k8s.io`), а не FluxCD |
| Networking/Tunnels/vpn_automation.md | Короткий раздел о FluxCD/ArgoCD |
| Kubernetes/Installation/RKE/rke_management_scenarios.md | Одна ссылка на файл Flux |
| CI-CD/GitLab_CI/Concepts/environments_and_deployments.md | Один путь `flux_resource_path` в примере |
| Kubernetes/Autoscaling/HPA/*.md | Упоминание в контексте конфликтов (теория) |
| Grafana/monitoring_as_code.md | Упоминание в контексте GitOps (без манифестов) |
| WebServers/Traefik/traefik-high-availability.md | Одна строка о GitOps |
| Networking/NetBox/netbox-enterprise-automation.md | Упоминание в контексте GitOps |
| Service_Mesh/istio-sidecar-configuration.md | Одна строка о Flux в Git-репозитории |
| Kubernetes/Base/Deployment/progressive_delivery.md | Ссылка на GitOps (без манифестов) |
| Kubernetes/Base/Deployment/index.md | Ссылка на GitOps (без манифестов) |
| Kubernetes/Base/Deployment/deployment_with_servicemesh.md | Ссылка на GitOps (без манифестов) |
| Kubernetes/ToolsUtilities/Helm/helm_chart_practical_scenarios.md | Одна строка в таблице |
