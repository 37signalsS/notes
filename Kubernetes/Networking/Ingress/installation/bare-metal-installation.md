# Ingress — установка через манифест (Bare-Metal)

## Определения

**Bare-Metal установка** — метод развертывания Ingress-контроллера путем прямого применения Kubernetes-манифестов без использования пакетных менеджеров (Helm). Обеспечивает полный контроль над всеми компонентами: `Namespace`, `ServiceAccount`, `ConfigMap`, `ClusterRole`, `Deployment`, `Service`.

**Ingress-контроллер** — приложение (обычно `Deployment` или `DaemonSet`), которое реализует правила, описанные в объекте `Ingress`. Без установленного контроллера объект `Ingress` не функционирует. Подробнее: [Ingress — обзор и основные концепции](../overview.md).

## Основные концепции

### Когда использовать установку через манифест

| Критерий | Манифест | Helm |
| :--- | :--- | :--- |
| **Контроль конфигурации** | Полный доступ ко всем ресурсам | Ограничен значениями `values.yaml` |
| **Среда** | Bare-metal, air-gapped, специализированные требования | Облачные среды, стандартные развертывания |
| **Сложность обновления** | Высокая (ручное слияние изменений) | Низкая (`helm upgrade`) |
| **Автоматизация** | Требует кастомных скриптов | Встроенная через Helm |
| **Аудит и версионирование** | Ручное управление манифестами | Встроенное управление версиями чартов |

**Рекомендация:** для стандартных сценариев предпочтительна [Ingress — установка через Helm](./helm-installation.md). Манифесты используются при наличии специфических требований к инфраструктуре.

## Практические сценарии

### 1. Получение базового манифеста

Скачайте `deploy.yaml` из официального репозитория [NGINX Ingress](https://github.com/kubernetes/ingress-nginx/tree/main/deploy/static/provider/baremetal):

```bash
curl -O https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/baremetal/deploy.yaml
```

Файл содержит все необходимые ресурсы для развертывания контроллера.

### 2. Настройка Service типа NodePort

Для bare-metal окружений без облачного LoadBalancer используется `NodePort`.

**Изменения в ресурсе `Service`:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: ingress-nginx-controller
  namespace: ingress-nginx
spec:
  type: NodePort
  externalTrafficPolicy: Local  # Сохраняет исходный IP клиента
  ports:
    - name: http
      port: 80
      targetPort: http
      nodePort: 31080  # Явное задание порта (опционально)
    - name: https
      port: 443
      targetPort: https
      nodePort: 31443  # Явное задание порта (опционально)
  selector:
    app.kubernetes.io/name: ingress-nginx
```

**Параметры:**

- `type: NodePort` — открывает сервис на портах всех узлов кластера в диапазоне 30000–32767
- `externalTrafficPolicy: Local` — трафик обрабатывается только на узлах с запущенными подами контроллера, сохраняется исходный IP клиента. Подробно: [NodePort](../../Service/service_type_nodeport.md#externaltrafficpolicy-local)
- `nodePort` — явное задание портов упрощает настройку firewall и внешних балансировщиков

**Важно:** `externalTrafficPolicy: Local` требует совместного использования с `nodeSelector` или affinity-правилами для гарантированного запуска подов контроллера на нужных узлах.

### 3. Определение кастомного IngressClass

Для предотвращения конфликтов при наличии нескольких Ingress-контроллеров определяется собственный класс.

**Изменения в `Deployment` (секция `args`):**

```yaml
spec:
  template:
    spec:
      containers:
        - name: controller
          args:
            - /nginx-ingress-controller
            - --ingress-class=system-ingress  # Кастомное имя класса
            - --configmap=$(POD_NAMESPACE)/ingress-nginx-controller
```

**Использование в Ingress-ресурсах:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
spec:
  ingressClassName: system-ingress  # Только этот контроллер будет обрабатывать
  rules:
    - host: api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: api-service
                port:
                  number: 80
```

### 4. Настройка высокой доступности (HA) через Pod Anti-Affinity

Для отказоустойчивости поды контроллера размещаются на разных узлах.

**Изменения в `Deployment` (секция `spec.template.spec`):**

```yaml
spec:
  template:
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: app.kubernetes.io/name
                    operator: In
                    values:
                      - ingress-nginx
              topologyKey: kubernetes.io/hostname
```

**Параметры:**

- `requiredDuringSchedulingIgnoredDuringExecution` — жесткое правило, запрещает планирование подов с одинаковым лейблом на одном узле
- `topologyKey: kubernetes.io/hostname` — правило применяется к узлам кластера
- `app.kubernetes.io/name: ingress-nginx` — лейбл для идентификации подов контроллера

**Рекомендация:** для HA-кластера установите `replicas: 2` или более в `Deployment`.

### 5. Включение JSON-логов

Для упрощения сбора и анализа логов настраивается вывод в формате JSON.

**Изменения в `ConfigMap` (`ingress-nginx-controller`):**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ingress-nginx-controller
  namespace: ingress-nginx
data:
  log-format-upstream: '{"time":"$time_iso8601","remote_addr":"$remote_addr","proxy_protocol_addr":"$proxy_protocol_addr","request_method":"$request_method","request_uri":"$request_uri","status":"$status","body_bytes_sent":"$body_bytes_sent","request_time":"$request_time","upstream_response_time":"$upstream_response_time"}'
  access-log: "true"
  use-forwarded-headers: "true"
```

**Поля формата:**

- `time_iso8601` — временная метка в ISO 8601
- `proxy_protocol_addr` — исходный IP клиента (при использовании PROXY protocol)
- `request_time` — общее время обработки запроса
- `upstream_response_time` — время ответа бэкенда

### 6. Применение кастомизированного манифеста

Сохраните изменения в файл `deploy-custom.yaml` и примените:

```bash
kubectl apply -f ./deploy-custom.yaml
```

**Проверка установки:**

```bash
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx
kubectl get ingressclass
```

## Дополнительная информация

### Смежные темы

- **[Ingress — обзор и основные концепции](../overview.md)** — базовые понятия маршрутизации и TLS.
- **[Ingress — установка через Helm](./helm-installation.md)** — основной метод установки в большинстве сред.
- **[Ingress-контроллеры — сравнение и выбор](../controllers_comparison.md)** — руководство по выбору решения.
- **[NodePort](../../Service/service_type_nodeport.md)** — подробное описание механизма работы и `externalTrafficPolicy`.
- **[Миграция с Ingress на Gateway API](../../gateway_api/migration.md)** — руководство по переходу на новую спецификацию.

Сообщество Kubernetes рекомендует переход на Gateway API — новую спецификацию для управления входящим трафиком. NGINX Ingress Controller продолжает поддерживаться, но новые функции разрабатываются в рамках Gateway API.
