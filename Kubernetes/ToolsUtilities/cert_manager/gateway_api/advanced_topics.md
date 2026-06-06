# Интеграция Cert-manager с Gateway API: Дополнительные темы

## Определения

**Hostname-конфликт** — ситуация, при которой cert-manager некорректно определяет домены для сертификата из-за указания `hostname` в слушателе Gateway.

**TLS Passthrough** — режим Gateway, при котором TLS-трафик передаётся напрямую бэкенду без терминации на шлюзе (статус ресурса TLSRoute: `v1alpha2`).

---

## Основные концепции

### Проблема hostname в Gateway

При указании `hostname` в спецификации слушателя Gateway cert-manager может некорректно определять домены для автоматической генерации Certificate.

**Причина:** cert-manager извлекает домены из поля `hostname` слушателя, что может конфликтовать с явным указанием `dnsNames` в Certificate.

**Решения:**

1. **Создать Certificate вручную** перед применением Gateway — явное определение `dnsNames` исключает неоднозначность
2. **Дождаться создания Secret** — cert-manager автоматически создаст Certificate при наличии аннотации на Gateway
3. **Применить Gateway с ссылкой на Secret** — после создания Secret указать его в `certificateRefs`

### Особенности TLS Passthrough

- Требуется ресурс `TLSRoute` (статус: `v1alpha2`, Alpha)
- cert-manager **не участвует** в терминации — бэкенд самостоятельно управляет сертификатами
- Подходит для сценариев mTLS, где backend валидирует клиентские сертификаты

### Wildcard-сертификаты

- Требуют **DNS-01 solver** в ClusterIssuer
- Один сертификат покрывает все поддомены
- Обновление [практических сценариев](./practical_scenarios.md) — пример wildcard-конфигурации

---

## Практические сценарии

### Диагностика интеграции

```bash
# Статус Gateway
kubectl get gateway -n <namespace>

# Детали Gateway (включая события и условия)
kubectl describe gateway <gateway-name> -n <namespace>

# Статус Certificate
kubectl get certificate -n <namespace>

# Статус Challenge (для ACME)
kubectl get challenge -n <namespace>

# Логи cert-manager (фильтр по Gateway)
kubectl logs -n cert-manager -l app=cert-manager --tail=200 | grep -i gateway
```

### Расширенная диагностика

```bash
# Проверка Gateway API CRD
kubectl get crd | grep gateway.networking.k8s.io

# Проверка флага --enable-gateway-api
kubectl get deployment cert-manager -n cert-manager -o jsonpath='{.spec.template.spec.containers[0].args}'

# Детали CertificateRequest
kubectl get certificaterequest -n <namespace>
kubectl describe certificaterequest <cr-name> -n <namespace>
```

---

## Дополнительная информация

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Gateway API not enabled` | Флаг `--enable-gateway-api` не указан | Пересоздать cert-manager с флагом (см. [Практические сценарии](./practical_scenarios.md)) |
| `CertificateRef not found` | Secret не создан или в другом namespace | Проверить статус Certificate, убедиться что Secret существует |
| `hostname конфликт` | cert-manager не определяет домен из Gateway | Создать Certificate вручную с явным указанием `dnsNames` |
| `CRD missing` | Gateway API CRD не установлены до cert-manager | Установить CRD: `kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.0.0/standard-install.yaml` |
| `Challenge pending` | DNS-01 solver не настроен или HTTP-01 недоступен | Проверить конфигурацию solver, убедиться что домен доступен извне |

### Смотрите также

- **[Миграция с Ingress на Gateway API](../../../Networking/gateway_api/migration.md)** — инструкции по переносу конфигураций
- **[Cert-manager: Установка](../../installation.md)** — включение Gateway API интеграции
- **[Практические сценарии](./practical_scenarios.md)** — использование сертификатов с Gateway
