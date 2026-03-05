# Ingress: Установка через манифест (Bare-Metal)

Для bare-metal окружений или в случаях, когда требуется тонкая настройка, можно установить Ingress-контроллер напрямую из официального манифеста, кастомизировав его под свои нужды. Этот подход дает полный контроль над всеми компонентами.

## 1. Получение манифеста

Скачайте `deploy.yaml` из официального [репозитория NGINX Ingress](https://github.com/kubernetes/ingress-nginx/tree/main/deploy/static/provider/baremetal). Этот файл содержит все необходимые ресурсы: `Namespace`, `ServiceAccount`, `ConfigMap`, `ClusterRole`, `Deployment` и др.

## 2. Ключевые кастомизации манифеста

В скачанном файле рекомендуется внести несколько изменений для повышения надежности и управляемости.

### а) Настройка Service типа `NodePort`

Найдите ресурс `Service` для контроллера и измените его `spec`:

- **`type: NodePort`**: Выставляет сервис на портах всех узлов.
- **`externalTrafficPolicy: Local`** (опционально, но рекомендуется): Заставляет `NodePort` открываться только на тех узлах, где запущены поды Ingress-контроллера. Это сохраняет исходный IP-адрес клиента и избегает лишнего сетевого хопа. *Требует совместного использования с `nodeSelector` или Affinity-правилами.*
- **`spec.ports`**: Можно явно задать `nodePort` для HTTP и HTTPS, например `31080` и `31443`.

### б) Определение кастомного `IngressClass`

Чтобы избежать конфликтов, если в кластере может быть несколько Ingress-контроллеров, рекомендуется определить собственный класс.

Найдите `Deployment` контроллера и в аргументах запуска (`args`) добавьте:

```yaml
- /nginx-ingress-controller
- --ingress-class=system-ingress # Наше кастомное имя
- --configmap=$(POD_NAMESPACE)/ingress-nginx-controller
```

Теперь только `Ingress`-ресурсы с аннотацией `kubernetes.io/ingress.class: system-ingress` или полем `spec.ingressClassName: system-ingress` будут обрабатываться этим контроллером.

### в) Настройка высокой доступности (HA) через Anti-Affinity

Чтобы два пода Ingress-контроллера не оказались на одном узле (что сведет на нет отказоустойчивость), используется `podAntiAffinity`.

В `Deployment` контроллера добавьте в `spec.template.spec`:

```yaml
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: app.kubernetes.io/name
                    operator: In
                    values:
                      - ingress-nginx
              topologyKey: "kubernetes.io/hostname"
```

- `requiredDuringScheduling...`: Жесткое правило, запрещающее планировщику размещать поды с одинаковым лейблом (`app.kubernetes.io/name: ingress-nginx`) на одном узле (`topologyKey: "kubernetes.io/hostname"`).

### г) Включение JSON-логов

Для упрощения сбора и анализа логов, настройте их вывод в формате JSON.
Найдите ресурс `ConfigMap` (`ingress-nginx-controller`) и добавьте в `data`:

```yaml
data:
  log-format-upstream: '{"time": "$time_iso8601", "proxy_protocol_addr": "$proxy_protocol_addr", ...}' # Добавьте нужный формат
  # Другие опции...
```

## 3. Применение манифеста

```bash
kubectl apply -f ./deploy-custom.yaml
```

Этот подход обеспечивает полный контроль и создает надежную, отказоустойчивую конфигурацию Ingress-контроллера.

---

## Ссылки

- **[Helm установка](./helm_installation.md)** — установка через Helm
- **[Практические сценарии](../practical_scenarios.md)** — TLS, аннотации, маршрутизация
