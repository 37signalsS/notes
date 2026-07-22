# Ingress — установка через манифест (Bare-Metal)

> [!CAUTION]
> **Внимание (март 2026):** Проект `kubernetes/ingress-nginx` официально перешел в статус **End of Life (EOL — завершение жизненного цикла)**. Поддержка прекращена, патчи безопасности не выпускаются. Для новых инсталляций в bare-metal средах настоятельно рекомендуется использовать решения на базе **Gateway API (Application Programming Interface)** или альтернативные контроллеры (например, **HAProxy** или **Traefik**).

## Определения

**Bare-Metal установка** — метод развертывания Ingress-контроллера путем прямого применения манифестов Kubernetes без использования пакетных менеджеров. Обеспечивает максимальный контроль над составом ресурсов: `Namespace`, `ServiceAccount`, `ConfigMap`, `ClusterRole`, `Deployment`, `Service`.

**Kustomize** — инструмент для декларативной настройки манифестов Kubernetes, встроенный в `kubectl`. Позволяет изменять базовые файлы без их прямого редактирования через оверлеи (overlays).

**Ingress-контроллер** — приложение (обычно `Deployment` или `DaemonSet`), которое реализует правила маршрутизации L7 (Layer 7). Подробнее: **[Ingress — обзор и основные концепции](../overview.md)**.

## Основные концепции

### Сравнение методов управления

| Критерий | Манифесты + Kustomize | Helm |
| :--- | :--- | :--- |
| **Контроль** | Полный (видны все YAML-поля) | Ограничен шаблонами чарта |
| **Среда** | Bare-metal, Air-gapped (изолированные сети) | Облака, стандартные окружения |
| **Обновление** | Ручное (через `kustomize build`) | Автоматическое (`helm upgrade`) |
| **Сложность** | Требует понимания структуры ресурсов | Скрывает детали реализации |

**Рекомендация:** Используйте установку через манифесты только в случаях, когда Helm недоступен или требуется нестандартная топология ресурсов, которую сложно описать через `values.yaml`.

---

## Практические сценарии

### 1. Подготовка структуры Kustomize

Вместо скачивания одного огромного файла `deploy.yaml`, рекомендуется использовать `kustomization.yaml` для управления базой и локальными правками.

```bash
mkdir -p ingress-setup && cd ingress-setup
```

Создайте файл `kustomization.yaml`:

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  # Ссылка на официальный базовый манифест для Bare-metal
  - https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/baremetal/deploy.yaml

patches:
  - path: service-patch.yaml
  - path: configmap-patch.yaml
```

### 2. Настройка Service через патч

Для Bare-metal без внешнего LoadBalancer (балансировщика нагрузки) необходимо настроить `NodePort` и обеспечить сохранение IP-адреса клиента.

Создайте файл `service-patch.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: ingress-nginx-controller
  namespace: ingress-nginx
spec:
  type: NodePort
  externalTrafficPolicy: Local # Сохранение исходного IP клиента
  ports:
    - name: http
      port: 80
      targetPort: http
      nodePort: 31080 # Статический порт (30000-32767)
    - name: https
      port: 443
      targetPort: https
      nodePort: 31443
```

**Нюанс:** Режим `externalTrafficPolicy: Local` отключает SNAT (Source Network Address Translation), позволяя приложению видеть реальный IP клиента, но требует, чтобы поды контроллера были запущены именно на тех узлах, куда приходит трафик. Подробнее: **[NodePort — механизмы работы](../../Service/service_type_nodeport.md)**.

### 3. Тонкая настройка через ConfigMap

Создайте файл `configmap-patch.yaml` для включения оптимизаций и логирования:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ingress-nginx-controller
  namespace: ingress-nginx
data:
  # Включение JSON-логов для систем сбора (ELK/Loki)
  log-format-upstream: '{"time":"$time_iso8601","remote_addr":"$remote_addr","status":"$status"}'
  # Оптимизация для работы за внешним прокси
  use-forwarded-headers: "true"
  compute-full-forwarded-for: "true"
```

### 4. Применение конфигурации

Используйте флаг `-k` для применения директории Kustomize:

```bash
kubectl apply -k .
# → namespace/ingress-nginx created
# → serviceaccount/ingress-nginx created
# → configmap/ingress-nginx-controller patched
# → service/ingress-nginx-controller patched
# → deployment.apps/ingress-nginx-controller created
```

### 5. Проверка состояния

```bash
kubectl get pods -n ingress-nginx
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → ingress-nginx-controller-78d59469-abcde   1/1     Running   0          2m

kubectl get svc -n ingress-nginx
# → NAME                       TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)                      AGE
# → ingress-nginx-controller   NodePort   10.96.123.45   <none>        80:31080/TCP,443:31443/TCP   2m
```

---

## Дополнительная информация

### Рекомендации по эксплуатации

- **High Availability (HA):** При установке через манифест не забудьте увеличить количество реплик в `Deployment` (по умолчанию часто `1`) и настроить `podAntiAffinity`, чтобы поды не оказывались на одном узле.
- **NodeSelector:** В bare-metal средах часто выделяют отдельные узлы под Ingress (Edge Nodes). Используйте `nodeSelector` в манифесте для жесткой привязки контроллера.
- **Обновление:** Перед обновлением всегда делайте `kubectl kustomize . > current-state.yaml` для аудита планируемых изменений.

### Смежные темы

- **[Ingress — установка через Helm](./helm-installation.md)** — стандартный метод для облачных сред.
- **[Ingress-контроллеры — сравнение](../controllers_comparison.md)** — выбор альтернатив после EOL NGINX.
- **[Gateway API — будущее маршрутизации](../../gateway_api/migration.md)** — подготовка к переезду на современный стандарт.
- **[MetalLB — LoadBalancer для Bare-metal](../../metallb.md)** — как получить `External-IP` без облака.
