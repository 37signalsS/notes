# Monitoring as Code (MaC): Grafana и GitOps

**Monitoring as Code (MaC)** — методология управления инфраструктурой наблюдаемости, при которой конфигурации инструментов (дашборды, источники данных, правила алертинга) описываются декларативно в виде кода, проходят через процесс Code Review и автоматически развертываются через CI/CD или GitOps-контроллеры.

## Определения

- **MaC (Monitoring as Code)**: Применение принципов Software Engineering (версионирование, тестирование, автоматизация) к процессам мониторинга.
- **GitOps в мониторинге**: Использование Git как единственного источника истины (**SSoT**) для всех объектов наблюдаемости. Изменения в Git автоматически синхронизируются с инстансами Grafana.
- **Dashboard-as-Code (DaC)**: Подмножество MaC, сфокусированное на генерации и управлении JSON-моделями дашбордов через шаблонизаторы.
- **Sidecar (k8s-sidecar)**: Вспомогательный контейнер, работающий рядом с Grafana, который обнаруживает ConfigMap с дашбордами в Kubernetes и загружает их "на лету".

---

## Базовые концепции

### Жизненный цикл MaC

Процесс управления мониторингом как кодом состоит из трех уровней:

1.  **Генерация (Generation)**: Использование языков высокого уровня (Jsonnet, Python) вместо ручного редактирования гигантских JSON-файлов.
2.  **Валидация (Validation)**: Проверка синтаксиса, линтинг PromQL-запросов и соблюдение стандартов оформления до деплоя.
3.  **Доставка (Delivery)**: Синхронизация кода с Grafana через API или нативные механизмы Kubernetes.

### Сравнение инструментов

| Инструмент | Подход | Когда использовать |
| :--- | :--- | :--- |
| **Grizzly** | CLI / YAML | Быстрая синхронизация дашбордов и алертов через API. Идеально для небольших команд. |
| **Terraform** | IaC / HCL | Управление всей инфраструктурой Grafana (пользователи, папки, источники данных, Cloud-инстансы). |
| **Jsonnet (Grafonnet)**| Templating | Массовое создание типовых дашбордов для сотен однотипных микросервисов. |
| **Crossplane** | K8s Control Plane | Управление ресурсами Grafana Cloud напрямую через манифесты Kubernetes. |
| **Grafana Operator** | K8s Operator | Нативное управление инстансами и дашбордами внутри кластера Kubernetes. |

---

## Практические сценарии

### Сценарий 1: GitOps через ConfigMap Sidecar (ArgoCD)

Это стандартный путь для Kubernetes-сред, использующих `kube-prometheus-stack`.

1.  **Описание дашборда**: Дашборд хранится в Git в виде JSON или генерируется из Jsonnet.
2.  **Манифест ConfigMap**:
    ```yaml
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: my-app-dashboard
      namespace: monitoring
      labels:
        grafana_dashboard: "1" # Метка для обнаружения sidecar-ом
      annotations:
        grafana_dashboard_folder: "Applications" # Автоматическое создание папки
    data:
      dashboard.json: |
        { ... JSON ... }
    ```
3.  **Синхронизация**: ArgoCD следит за репозиторием и обновляет ConfigMap. Sidecar в поде Grafana замечает изменение и обновляет дашборд в интерфейсе без перезагрузки.

### Сценарий 2: Использование Grizzly для CI/CD пайплайнов

**Grizzly** (`grzl`) — утилита от Grafana Labs, позволяющая управлять ресурсами через YAML-обертки над JSON-моделями.

**Пайплайн валидации (GitLab CI):**
```yaml
validate_dashboards:
  stage: test
  image: grafana/grizzly:latest
  script:
    - grzl lint dashboards/ # Проверка синтаксиса и структуры
    - dashboard-linter lint my-dashboard.json # Глубокая проверка PromQL
```

**Пайплайн деплоя:**
```yaml
deploy_prod:
  stage: deploy
  script:
    - grzl push dashboards/ --endpoint $GRAFANA_URL --token $GRAFANA_TOKEN
```

### Сценарий 3: Terraform для Managed Grafana (Grafana Cloud)

Для управления пользователями, плагинами и источниками данных в облачной или корпоративной Grafana рекомендуется использовать официальный провайдер.

```hcl
resource "grafana_dashboard" "metrics" {
  config_json = file("dashboards/service_metrics.json")
  folder      = grafana_folder.team_a.id
  overwrite   = true
}

resource "grafana_service_account" "ci_cd" {
  name = "CI/CD Deployer"
  role = "Admin"
}
```

---

## Дополнительная информация

### Рекомендации по эксплуатации

- **Стабильные UID**: Всегда фиксируйте `uid` в JSON дашборда. Если Grafana создаст случайный UID при импорте, ссылки между дашбордами сломаются.
- **Запрет ручного редактирования**: В настройках провайдера (Provisioning) или через RBAC установите `editable: false`. Это предотвратит ситуацию "дрейфа конфигурации" (Configuration Drift), когда правки в UI затираются кодом из Git.
- **Версионирование в именах**: Добавляйте версию или хеш коммита в метаданные дашборда для быстрого сопоставления интерфейса с состоянием в Git.
- **Проверка алертов**: При использовании MaC алерты должны тестироваться в CI через `promtool` (для Prometheus) или встроенные средства валидации Grizzly.

### Типичные ошибки

- **Хранение секретов в Git**: Пароли от источников данных должны передаваться через переменные окружения или внешние секреты (Vault, AWS Secrets Manager), а не жестко прописываться в коде MaC.
- **Огромные ConfigMap**: Лимит размера ConfigMap в Kubernetes — 1 МБ. Очень сложные дашборды могут не поместиться в один ресурс. В таких случаях используйте разделение на несколько файлов или деплой через API (Grizzly/Terraform).
- **Отсутствие папок**: Без указания аннотации `grafana_dashboard_folder` все дашборды попадут в папку `General`, что затруднит навигацию.

> **См. также:**
> - **[Провиженинг Grafana](./grafana_provisioning.md)** — механизмы и конфигурация провайдеров.
> - **[Дашборды: Best Practices](./grafana-dashboards.md)** — рекомендации по проектированию визуализаций.
> - **[Интеграция с Prometheus Operator](../Prometheus/kubernetes/operator/grafana_integration.md)** — детальная работа sidecar-контейнера.
