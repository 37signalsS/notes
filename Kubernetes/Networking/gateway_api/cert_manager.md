# Интеграция Gateway API с cert-manager

## Интеграция с cert-manager

Для выпуска сертификатов через Gateway API необходимо:

1. **Установить cert-manager с поддержкой Gateway API:**

```bash
helm install cert-manager jetstack/cert-manager \
  --set "extraArgs={--enable-gateway-api=true}" \
  -n cert-manager --create-namespace
```

**Важно:** CRD Gateway API должны быть установлены ДО cert-manager, иначе возникнет ошибка.

2. **Создать Issuer/ClusterIssuer:**

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: selfsigned-ca
  namespace: sample
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: sample-tls
  namespace: sample
spec:
  secretName: sample-tls
  issuerRef:
    name: selfsigned-ca
    kind: Issuer
  dnsNames:
  - sample.example.local
```

3. **Ссылка на Secret в Gateway:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: example-gateway
spec:
  gatewayClassName: ig
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: sample-tls
        namespace: sample
```

### Особенности работы с HTTPS

При использовании `hostname` в Gateway и cert-manager возможны проблемы с генерацией сертификата. В некоторых случаях требуется:
- Удалить поле `hostname` из манифеста Gateway
- Создать Certificate вручную перед созданием Gateway
- Дождаться создания Secret и только затем применять Gateway

### Сценарий: несколько HTTPS-слушателей

Gateway API и `cert-manager` корректно обрабатывают сценарии с несколькими `listener` для разных доменов на одном шлюзе.

```yaml
# Gateway с двумя HTTPS-слушателями для разных хостов
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: multi-tls-gateway
spec:
  gatewayClassName: traefik
  listeners:
  - name: https-main
    hostname: "main.example.com"
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: main-tls-secret
  - name: https-secondary
    hostname: "secondary.example.com"
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: secondary-tls-secret
```

`cert-manager` обнаружит оба `hostname` и запросит для каждого свой сертификат, если в `Gateway` указаны соответствующие аннотации или если `Certificate` созданы вручную. Это подтверждает зрелость интеграции.

---

**См. также:**
- [Traefik](./traefik.md) — пример настройки Gateway с TLS
- [Envoy Gateway](./envoy_gateway.md) — пример настройки Gateway
- [Базовые сценарии](./practical_basic.md) — основы создания Gateway

**Parent:** [Gateway API](../gateway_api.md)
