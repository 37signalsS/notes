# Cert-manager: Интеграция с Ingress

## Определения

**Ingress-интеграция cert-manager** — функциональность автоматизированного управления жизненным циклом TLS-сертификатов для ресурсов Ingress. Позволяет делегировать выпуск и продление сертификатов контроллеру cert-manager без необходимости ручного создания объектов `Certificate`.

**ingress-shim** — вспомогательный контроллер в составе основного бинарного файла cert-manager. Он отслеживает объекты Ingress и, основываясь на наличии специфических аннотаций, автоматически генерирует и поддерживает соответствующие ресурсы `Certificate`.

**Преимущества подхода:**
- **Декларативность:** Конфигурация TLS описывается непосредственно в объекте Ingress.
- **Автоматизация:** Полный цикл — от заказа сертификата у CA (Let's Encrypt, Vault и др.) до его ротации в Secret.
- **Универсальность:** Поддержка всех популярных Ingress-контроллеров (NGINX, Traefik, HAProxy, AWS ALB, GCE).

> **См. также:** [Cert-manager: Определения и основные понятия](../definitions.md) — обзор CRD, типов Issuer и архитектуры.

---

## Основные концепции

### Механизм работы ingress-shim

Контроллер `ingress-shim` реализует реактивную модель управления:

1.  **Наблюдение:** Контроллер мониторит API-сервер на предмет событий `create` и `update` для ресурсов Ingress.
2.  **Фильтрация:** Проверяется наличие аннотаций выбора Issuer (например, `cert-manager.io/cluster-issuer`). Если аннотаций нет, Ingress игнорируется.
3.  **Генерация Certificate:**
    - Создается ресурс `Certificate` в том же Namespace, что и Ingress.
    - Имя ресурса по умолчанию формируется как `name-of-ingress-tls-name` или задается аннотацией `cert-manager.io/certificate-name`.
    - Поля `dnsNames` заполняются из `spec.tls[].hosts`.
    - Поле `secretName` берется из `spec.tls[].secretName`.
4.  **Установка OwnerReference:** Созданный `Certificate` получает `ownerReference`, указывающий на родительский Ingress. При удалении Ingress ресурс `Certificate` будет удален автоматически (Garbage Collection).

### Взаимодействие с IngressClass

cert-manager может фильтровать Ingress по классам. При использовании ACME (HTTP-01) важно, чтобы `ingressClassName` в Ingress совпадал с конфигурацией Solver в Issuer. Аннотация `acme.cert-manager.io/http01-ingress-class` позволяет переопределить класс для временных Ingress, создаваемых в процессе проверки.

### Специфика 2026 года

- **ARI (ACME Renewal Information):** Поддержка протокола, позволяющего CA динамически определять оптимальное время продления сертификата.
- **Алгоритмы:** Полный переход на **Ed25519** и **ECDSA (P-256/384)** как стандарты безопасности по умолчанию.
- **Короткие сертификаты:** Let's Encrypt и другие CA перешли на 45-дневные циклы (вместо 90), что делает автоматизацию через cert-manager критически важной.

---

## Аннотации cert-manager для Ingress

### Выбор и настройка Issuer

| Аннотация | Описание | Значение |
| :--- | :--- | :--- |
| `cert-manager.io/issuer` | Использовать Issuer в том же Namespace | `имя-issuer` |
| `cert-manager.io/cluster-issuer` | Использовать общекластерный ClusterIssuer | `имя-cluster-issuer` |
| `kubernetes.io/tls-acme: "true"` | Использовать Issuer по умолчанию (флаги `--default-issuer-*`) | `"true"` |
| `cert-manager.io/issuer-kind` | Явное указание типа (если не Issuer) | `ClusterIssuer`, `Issuer` |
| `cert-manager.io/issuer-group` | Группа API для Issuer | `cert-manager.io` (по умолчанию) |

### Параметры выпуска Certificate

| Аннотация | Описание | Значение по умолчанию / Пример |
| :--- | :--- | :--- |
| `cert-manager.io/certificate-name` | Явное имя для ресурса Certificate | `my-custom-cert-name` |
| `cert-manager.io/common-name` | Установка Common Name (CN) сертификата | `example.com` |
| `cert-manager.io/duration` | Срок действия сертификата | `1080h` (45 дней) |
| `cert-manager.io/renew-before` | За сколько до окончания начать продление | `168h` (7 дней) |
| `cert-manager.io/usages` | Key Usages (через запятую) | `server auth, client auth` |
| `cert-manager.io/issue-temporary-certificate` | Выпуск временного сертификата до ACME | `"true"` |

### Безопасность и приватные ключи

| Аннотация | Описание | Пример |
| :--- | :--- | :--- |
| `cert-manager.io/private-key-algorithm` | Алгоритм генерации ключа | `ECDSA`, `Ed25519`, `RSA` |
| `cert-manager.io/private-key-size` | Размер ключа (для RSA/ECDSA) | `256`, `384`, `4096` |
| `cert-manager.io/private-key-rotation-policy` | Ротация ключа при каждом обновлении | `Always` (рекомендуется) |

### Специфичные для ACME (HTTP-01)

| Аннотация | Описание | Применение |
| :--- | :--- | :--- |
| `acme.cert-manager.io/http01-edit-in-place` | Не создавать новый Ingress для проверки | AWS ALB, GCE Ingress, Cloudflare |
| `acme.cert-manager.io/http01-ingress-class` | Класс Ingress для временных ресурсов | Если отличается от основного |

---

## Практические сценарии

### Базовая конфигурация (Standard 2026)

Для большинства случаев достаточно указать ClusterIssuer и политику ротации ключей.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp-ingress
  annotations:
    # 1. Выбор выпускающего органа
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    # 2. Современный стандарт безопасности
    cert-manager.io/private-key-algorithm: "ECDSA"
    cert-manager.io/private-key-rotation-policy: "Always"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - myapp.example.com
    secretName: myapp-tls-secret
  rules:
  - host: myapp.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: myapp-svc
            port:
              number: 80
```

> **Детальные примеры:** [Сценарии интеграции](./scenarios.md) — разбор случаев с Wildcard, SAN, несколькими TLS-секретами и временными сертификатами.

---

## Дополнительная информация

### Управление ресурсами и очистка

- **Удаление:** Когда вы удаляете Ingress, `ingress-shim` удаляет созданный им `Certificate`. Однако **Secret с сертификатом остается в кластере** для предотвращения случайной потери данных. Очистка секретов выполняется администратором или внешними инструментами.
- **Изменение hosts:** При добавлении или удалении хостов в секции `tls` объекта Ingress, cert-manager автоматически обновит ресурс `Certificate` и инициирует перевыпуск.

### Диагностика и Troubleshooting

Основным инструментом диагностики является утилита `cmctl` и анализ событий Kubernetes.

#### 1. Использование cmctl
```bash
# Полный статус цепочки выпуска (Certificate -> Request -> Order -> Challenge)
cmctl status certificate myapp-tls-secret -n <namespace>

# Проверка валидности Issuer
cmctl check api
```

#### 2. Проверка событий (Events)
Если сертификат не выпускается, проверьте события в Ingress и Certificate:
```bash
kubectl describe ingress myapp-ingress
kubectl describe certificate myapp-tls-secret
```

#### 3. Частые проблемы и решения

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| `Certificate` не создается | Отсутствует аннотация или опечатка в имени Issuer | Проверьте `metadata.annotations` |
| `Challenge` висит в `Pending` | Порт 80 закрыт или DNS не указывает на кластер | Проверить внешнюю доступность для HTTP-01 |
| `Issuer not found` | Namespace Issuer не совпадает с Ingress | Используйте `ClusterIssuer` для кросс-namespace работы |
| Ошибка `Forbidden` в AWS ALB | Не включен `http01-edit-in-place` | Добавьте аннотацию `acme.cert-manager.io/http01-edit-in-place: "true"` |

### Связанные документы

- **[Cert-manager: Определения](../definitions.md)** — база знаний по CRD и архитектуре.
- **[Gateway API: TLS](../gateway_api/definitions_and_concepts.md)** — современная альтернатива Ingress-интеграции.
- **[Let's Encrypt](../LetsEncrypt/index.md)** — настройка ACME-проверок и лимиты.
- **[Administration](../Administration/index.md)** — тюнинг контроллера и мониторинг.
- **[Ingress: Обзор](../../../Networking/Ingress/overview.md)** — сетевая архитектура в Kubernetes.
