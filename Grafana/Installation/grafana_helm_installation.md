# Установка Grafana в Kubernetes с использованием Helm

> **Навигация:**
> - [Обзор Grafana](../grafana_overview.md) — основная информация о платформе
> - [Провиженинг](../grafana_provisioning.md) — управление конфигурацией как код
> - [Источники данных](../grafana_datasources.md) — подключение систем мониторинга
> - [Установка через Docker Compose](./docker_compose_setup.md) — для standalone-развертывания

## Определения

- **Helm-чарт Grafana** — это пакет преднастроенных ресурсов Kubernetes, который автоматизирует установку, обновление и управление Grafana в кластере.
- **`values.yaml`** — файл конфигурации, используемый для кастомизации Helm-чарта перед установкой.

> **Примечание:** Для установки полного стека мониторинга (Prometheus + Grafana + Alertmanager) см. [kube-prometheus-stack: Практические сценарии](../../Prometheus/Kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios.md).

> **КРИТИЧЕСКИ ВАЖНО: Миграция Helm-репозитория (30 января 2026)**
>
> Официальный репозиторий `grafana https://grafana.github.io/helm-charts` **более не обновляется**.
>
> **Новый репозиторий:**
> ```bash
> helm repo add grafana-community https://grafana-community.github.io/helm-charts
> helm repo update
> ```
>
> **Затронутые чарты:** `grafana`, `grafana-mcp`, `synthetic-monitoring-agent`, `tempo`, `tempo-distributed`, `tempo-vulture`
>
> **Чарты НЕ затронуты:** `mimir`, `loki` (остаются в старых репозиториях)
>
> См. подробности: [Grafana Helm Charts Migration](https://iits-consulting.de/blog/grafana-helm-charts-moved-what-do)

## Основные концепции

- **Персистентность (Persistence)**: Обеспечивает сохранение данных Grafana (дашборды, источники данных, настройки) между перезапусками подов. Для этого используется PersistentVolumeClaim (PVC), что критически важно для продуктивных сред, чтобы избежать потери данных при сбоях или обновлениях.

- **Внешний доступ (Ingress)**: Ресурс Kubernetes, который настраивает правила для предоставления доступа к веб-интерфейсу Grafana извне кластера через контроллер (например, Nginx).

- **`root_url`**: Ключевой параметр конфигурации в `grafana.ini`, определяющий публичный URL-адрес Grafana. Он используется для генерации корректных ссылок в уведомлениях, приглашениях и других компонентах интерфейса. Неправильная настройка этого параметра — частая причина ошибок.

- **Provisioning**: Механизм автоматической загрузки и настройки ресурсов (дашбордов, источников данных) при старте Grafana. В Helm-чарте это часто реализуется через **`sidecar`**, который отслеживает ConfigMaps с определениями дашбордов и автоматически загружает их в Grafana.

- **Image Renderer**: Отдельный компонент, который позволяет Grafana создавать PNG-изображения графиков для включения в уведомления об алертах. Он использует headless-браузер и является обязательным для отправки алертов с визуализациями в мессенджеры, такие как Slack или Telegram.

## Практические сценарии

### Шаг 1: Подключение репозитория Helm

```bash
# Новый репозиторий (после 30 января 2026)
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# Старый репозиторий (только для legacy-систем, обновления не выходят)
# helm repo add grafana https://grafana.github.io/helm-charts
```

> **Примечание:** После 30.01.2026 используйте только репозиторий `grafana-community`. Старый репозиторий не получает новых версий, багфиксов и патчей безопасности.

### Шаг 2: Создание файла конфигурации

Создайте файл `grafana-values.yaml` с основными параметрами. Этот файл определяет ключевые аспекты развертывания.

> **Актуальные версии (февраль 2026):**
> - **Grafana:** 11.x.x (последняя стабильная)
> - **Helm-чарт grafana:** 10.5.x+ (из нового репозитория `grafana-community`)
> - **Минимальная версия Kubernetes:** 1.25+

**Пример `grafana-values.yaml`:**

```yaml
# Настройка Ingress для внешнего доступа
ingress:
  enabled: true
  ingressClassName: nginx
  annotations:
    # Для защиты можно использовать OAuth2 Proxy, развернутый отдельно
    # nginx.ingress.kubernetes.io/auth-url: "http://oauth2-proxy.default.svc.cluster.local/oauth2/auth"
    # nginx.ingress.kubernetes.io/auth-signin: "https://sso.your-domain.com/oauth2/start?rd=$request_uri"
  hosts:
    - host: grafana.your-domain.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - hosts:
        - grafana.your-domain.com
      secretName: grafana-tls

# Учетные данные администратора (рекомендуется использовать секреты)
admin:
  user: admin
  password: StrongPassword.123

# Включение персистентного хранилища для данных Grafana
persistence:
  enabled: true
  type: pvc
  size: 5Gi

# Указание публичного URL для корректной работы ссылок
grafana.ini:
  server:
    root_url: "https://grafana.your-domain.com"

# Включение автоматической загрузки дашбордов через sidecar
sidecar:
  dashboards:
    enabled: true
    label: grafana_dashboard
    labelValue: "1"

# Включение рендеринга изображений для алертов
imageRenderer:
  enabled: true

# Безопасность (production)
security:
  # Запуск от непривилегированного пользователя
  runAsUser: 472
  runAsGroup: 472
  fsGroup: 472
  
# Ресурсы (production)
resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 256Mi

# Сетевая политика
networkPolicy:
  enabled: true
  # Разрешить трафик только из определенных namespace
  ingress:
    from:
      - namespaceSelector:
          matchLabels:
            name: monitoring
```

> **Best Practices:**
> - Используйте **секреты** для чувствительных данных (пароли, API-ключи) через `admin.existingSecret` или внешние системы (Vault)
> - Включайте **NetworkPolicy** для ограничения сетевого доступа
> - Настраивайте **resource limits** для предотвращения исчерпания ресурсов кластера
> - Используйте **podDisruptionBudget** для обеспечения доступности во время обновлений

### Шаг 3: Установка Grafana

Выполнение установки с помощью `helm install`, используя созданный файл конфигурации.

```bash
helm install grafana grafana/grafana \
  -f grafana-values.yaml \
  --namespace monitoring --create-namespace \
  --wait --atomic
```

- `--wait`: Ожидать завершения развертывания всех ресурсов.
- `--atomic`: Откатить релиз в случае неудачной установки.

### Шаг 4: Проверка установки

Проверка статуса подов и Ingress-ресурса Grafana.

```bash
# Проверка статуса пода
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana

# Проверка созданного Ingress-ресурса
kubectl get ingress -n monitoring -l app.kubernetes.io/name=grafana
```

Убедитесь, что под находится в состоянии `Running`, а Ingress-ресурс корректно создан.

### Шаг 5: Доступ к Grafana

После успешного развертывания Grafana будет доступна по адресу, указанному в `ingress.hosts`. Для входа используйте учетные данные администратора.

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Pod в статусе `Pending`** | Нет доступных PV | Проверьте `kubectl get pvc -n monitoring` |
| **Pod в статусе `CrashLoopBackOff`** | Ошибка конфигурации | Проверьте логи: `kubectl logs -n monitoring -l app.kubernetes.io/name=grafana` |
| **Ingress не работает** | Неправильный `ingressClassName` | Убедитесь, что контроллер существует: `kubectl get ingressclass` |
| **404 при доступе** | Неправильный `root_url` | Проверьте `grafana.ini.server.root_url` в `values.yaml` |
| **Не загружаются дашборды** | Sidecar не находит ConfigMap | Проверьте метки: `kubectl get configmap -l grafana_dashboard=1` |
| **OOMKilled** | Мало памяти | Увеличьте `resources.limits.memory` |

**Полезные команды:**

```bash
# Просмотр статуса релиза
helm status grafana -n monitoring

# История обновлений
helm history grafana -n monitoring

# Откат к предыдущей версии
helm rollback grafana -n monitoring

# Удаление релиза
helm uninstall grafana -n monitoring
```

## Дополнительная информация

Для ознакомления со всеми доступными параметрами конфигурации Helm-чарта Grafana рекомендуется изучить его `values.yaml` по умолчанию.

```bash
helm show values grafana-community/grafana > grafana-default-values.yaml
```

Эта команда создаст файл `grafana-default-values.yaml` с полным списком опций и их значениями по умолчанию.

### Production Checklist

Перед развертыванием в production убедитесь:

- [ ] **Версии зафиксированы:** Используете конкретную версию чарта (`--version 10.5.8`), а не `latest`
- [ ] **Секреты защищены:** Пароли хранятся в Kubernetes Secrets или Vault, а не в `values.yaml`
- [ ] **Персистентность включена:** `persistence.enabled: true` с appropriate storage class
- [ ] **Resource limits настроены:** `resources.limits` для CPU и memory
- [ ] **Security context:** Запуск от непривилегированного пользователя (`runAsUser: 472`)
- [ ] **NetworkPolicy:** Ограничен входящий/исходящий трафик
- [ ] **Backup настроен:** Регулярный бэкап PostgreSQL/MySQL (для HA) или PVC
- [ ] **Monitoring включен:** ServiceMonitor для сбора метрик самой Grafana
- [ ] **HA готов:** Несколько реплик для production (`replicas: 2+`)

### Ссылки

- [Официальная документация Grafana](https://grafana.com/docs/grafana/latest/)
- [Helm-чарт grafana-community](https://github.com/grafana-community/helm-charts)
- [Grafana на Artifact Hub](https://artifacthub.io/packages/helm/grafana-community/grafana)
- [Миграция Helm-чартов (30.01.2026)](https://iits-consulting.de/blog/grafana-helm-charts-moved-what-do)
