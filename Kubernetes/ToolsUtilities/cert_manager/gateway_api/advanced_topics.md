# Интеграция Cert-manager с Gateway API: Дополнительные темы

## Определения

**Hostname-конфликт** — логическая ошибка, при которой контроллер `gateway-shim` (в составе cert-manager) пытается выпустить сертификат на основе поля `hostname` в `Listener`, в то время как пользователь уже определил `dnsNames` в ресурсе `Certificate` или другом `Listener`.

**TLS Passthrough** — режим Gateway, при котором TLS-трафик передаётся напрямую бэкенду без терминации на шлюзе (статус ресурса TLSRoute: `v1alpha2`). cert-manager в этом режиме не участвует в терминации.

**gateway-shim** — внутренний компонент cert-manager, который отслеживает ресурсы Gateway и ListenerSet и автоматически создает ресурсы `Certificate` на основе аннотаций.

**Dedicated Challenge Gateway** — архитектурный паттерн, при котором для прохождения HTTP-01 проверок используется отдельный шлюз (Gateway), изолированный от продуктового трафика.

---

## Основные концепции

### Проблема hostname в Gateway

При указании `hostname` в спецификации слушателя Gateway cert-manager может некорректно определять домены для автоматической генерации Certificate.

**Причина:** cert-manager извлекает домены из поля `hostname` слушателя, что может конфликтовать с явным указанием `dnsNames` в Certificate.

**Решения:**
1. **Создать Certificate вручную** перед применением Gateway — явное определение `dnsNames` исключает неоднозначность.
2. **Дождаться создания Secret** — cert-manager автоматически создаст Certificate при наличии аннотации на Gateway.
3. **Применить Gateway с ссылкой на Secret** — после создания Secret указать его в `certificateRefs`.
4. **Явное указание в Listener:** Всегда заполняйте поле `hostname` в слушателе, если планируете использовать аннотации. Если поле пустое (Wildcard в терминах Gateway API), автоматический выпуск через аннотации может завершиться ошибкой.

### Особенности TLS Passthrough

- Требуется ресурс `TLSRoute` (статус: `v1alpha2`, Alpha).
- cert-manager **не участвует** в терминации — бэкенд самостоятельно управляет сертификатами.
- Подходит для сценариев mTLS, где backend валидирует клиентские сертификаты.

### Безопасность: ReferenceGrant для TLS

В мультитенентных кластерах часто возникает ситуация, когда Gateway в одном namespace (`infra`) должен использовать Secret из другого (`app`).
- **Namespace `app`**: содержит `Certificate` и `Secret`.
- **Namespace `infra`**: содержит `Gateway`.

Чтобы шлюз получил доступ к секрету, необходимо создать `ReferenceGrant` в пространстве имен `app`. Без него контроллер шлюза (например, Envoy Gateway) выдаст ошибку доступа к TLS-ключам.

---

## Практические сценарии

### Диагностика интеграции (Базовая)

```bash
# Статус Gateway
kubectl get gateway -n <namespace>

# Детали Gateway (включая события и условия)
kubectl describe gateway <gateway-name> -n <namespace>

# Статус Certificate и Challenge
kubectl get certificate,challenge -n <namespace>

# Логи cert-manager (фильтр по Gateway)
kubectl logs -n cert-manager -l app=cert-manager --tail=200 | grep -i gateway
```

### Глубокая диагностика и отладка

1. **Проверка Gateway API CRD и версий:**
   ```bash
   kubectl get crd | grep gateway.networking.k8s.io
   # Проверка поддержки версий (требуется v1.0+)
   kubectl get gatewayclasses -o jsonpath='{.items[*].spec.controllerName}'
   ```

2. **Проверка флага --enable-gateway-api:**
   ```bash
   kubectl get deployment cert-manager -n cert-manager -o jsonpath='{.spec.template.spec.containers[0].args}'
   ```

3. **Анализ цепочки CertificateRequest:**
   ```bash
   # Если Certificate завис в состоянии False
   kubectl get certificaterequest -n <namespace>
   kubectl describe certificaterequest <cr-name> -n <namespace>
   ```

4. **Отслеживание временных HTTPRoute (для HTTP-01):**
   При прохождении проверки cert-manager создает временный маршрут для челленджа.
   ```bash
   kubectl get httproute -A | grep "acme-http-01"
   # Проверьте, привязан ли он к вашему Gateway (Admitted: True)
   kubectl describe httproute <name>
   ```

### Настройка Dedicated Challenge Gateway

В `ClusterIssuer` это настраивается через `http01.gatewayHTTPRoute`:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    solvers:
    - http01:
        gatewayHTTPRoute:
          parentRefs:
          - name: acme-challenge-gateway
            namespace: cert-manager
            kind: Gateway
```

---

## Дополнительная информация

### Частые ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Gateway API not enabled` | Флаг `--enable-gateway-api` не указан | Добавить флаг в Deployment или Helm-чарт cert-manager. |
| `CertificateRef not found` | Secret не создан или в другом namespace | Проверить статус Certificate и наличие `ReferenceGrant`. |
| `hostname конфликт` | cert-manager не определяет домен из Gateway | Заполнить `hostname` в Listener или создать Certificate вручную. |
| `CRD missing` | Gateway API CRD не установлены | `kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.0.0/standard-install.yaml` |
| `Challenge pending` | DNS-01 не настроен или HTTP-01 недоступен | Проверить доступность 80 порта извне и логи `challenge`. |
| `Forbidden Secret reference` | Нет прав на чтение секрета | Создать `ReferenceGrant` в целевом namespace. |

### Особенности версий (на июль 2026 г.)

- **cert-manager v1.20+**: Полная поддержка `ListenerSet`. Рекомендуется использовать для динамического Self-Service TLS.
- **Gateway API v1.5+**: Введена поддержка GRPCRoute и улучшена валидация. Переход на Gateway API обязателен, так как `ingress-nginx` в статусе EOL.

### Смотрите также

- **[Практические сценарии](./practical_scenarios.md)** — полные YAML-примеры конфигураций.
- **[Определения и концепции](./definitions_and_concepts.md)** — ролевая модель и ReferenceGrant.
- **[Миграция с Ingress](../../../Networking/gateway_api/migration.md)** — инструкции по переносу.
