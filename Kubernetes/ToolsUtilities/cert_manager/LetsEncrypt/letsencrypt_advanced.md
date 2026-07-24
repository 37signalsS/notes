# Let's Encrypt: Диагностика и решение проблем

## Определения

**ACME-ошибки Let's Encrypt** — ошибки, возвращаемые API-сервером Let's Encrypt (RFC 8555) при взаимодействии с контроллером cert-manager в процессе выпуска или продления сертификатов.

**Иерархия ресурсов (Resource Archaeology)** — метод последовательной диагностики цепочки объектов Kubernetes (Certificate → CertificateRequest → Order → Challenge) для выявления точного места сбоя.

**Self-check** — предварительная проверка cert-manager, в ходе которой контроллер пытается сам обратиться к HTTP-01 или DNS-01 токену перед тем, как уведомить Let's Encrypt о готовности.

> **Общая диагностика cert-manager:** [Administration troubleshooting](../Administration/troubleshooting.md)

---

## Основные концепции

### Иерархия диагностики (The "Archaeology" Flow)

Если объект `Certificate` не переходит в статус `Ready: True`, необходимо спускаться вниз по цепочке ресурсов до самого нижнего уровня. Ошибка почти всегда находится в `Challenge`.

1. **Certificate**: Отражает общее состояние.
2. **CertificateRequest**: Содержит статус формирования CSR и ожидания ответа от Issuer.
3. **Order**: Отражает состояние заказа в Let's Encrypt (pending, processing, valid, invalid).
4. **Challenge**: Содержит детали конкретной проверки (HTTP-01 или DNS-01).

### Типовые ACME-коды ошибок

| Код | Тип ошибки | Описание | Решение |
| :--- | :--- | :--- | :--- |
| `400` | `malformed` | Некорректный запрос или просроченный челлендж | Удалить Challenge, чтобы спровоцировать пересоздание |
| `403` | `unauthorized` | Ошибка авторизации (неверный DNS/HTTP ответ) | Проверить сетевую доступность или права DNS API |
| `429` | `rateLimited` | Превышен лимит запросов | Использовать Staging или ждать сброса лимита |
| `500` | `serverInternal` | Сбой на стороне Let's Encrypt | Повторить попытку позже |

### Лимиты Let's Encrypt (Rate Limits)

| Лимит | Значение | Период | Сброс |
| :--- | :--- | :--- | :--- |
| **Certificates per Domain** | 50 | 7 дней | Скользящее окно |
| **Duplicate Certificates** | 5 | 7 дней | **ARI позволяет обойти этот лимит** |
| **Failed Validation** | 5 | 1 час | По IP + домен |
| **New Orders per Account** | 300 | 3 часа | По аккаунту |

---

## Практические сценарии

### Глубокая диагностика цепочки ресурсов

```bash
# 1. Поиск проблемных сертификатов
kubectl get certificate -A | grep -v "True"

# 2. Осмотр CertificateRequest (найти последний созданный)
kubectl describe certificaterequest <name>

# 3. Осмотр Order
kubectl describe order <name>

# 4. Анализ Challenge (основной источник ошибок)
kubectl describe challenge <name>

# 5. Мониторинг процесса в реальном времени
watch kubectl get challenges -A
```

### Проблемы HTTP-01 проверки

**Симптом:** `Waiting for HTTP-01 challenge propagation: failed to perform self check`.

| Причина | Решение |
| :--- | :--- |
| **Hairpin NAT / Внутренняя сеть** | Кластер не может достучаться до своего внешнего IP. Настройте `split-horizon DNS` или используйте DNS-01. |
| **Принудительный HTTPS редирект** | Добавьте исключение для пути `/.well-known/acme-challenge/*` в конфигурации Ingress. |
| **Отсутствие TLS секрета** | Ingress-контроллер (например, Nginx) может возвращать 404/503 без сертификата. Используйте аннотацию `cert-manager.io/issue-temporary-certificate: "true"`. |
| **Ingress Edit-in-Place** | Если контроллер не создает новый Ingress для челленджа, добавьте в Issuer: `acme.cert-manager.io/http01-edit-in-place: "true"`. |

### Проблемы DNS-01 проверки

**Симптом:** `DNS problem: NXDOMAIN looking up TXT for _acme-challenge.example.com`.

1. **Проверка изнутри кластера**:
   ```bash
   kubectl run -it --rm --restart=Never dnsutils --image=tutum/dnsutils -- dig TXT _acme-challenge.example.com
   ```
2. **Recursive Nameservers**: Если кластер использует внутренний DNS, он может не видеть внешние записи. Укажите публичные DNS в аргументах контроллера cert-manager:
   ```bash
   --dns01-recursive-nameservers=8.8.8.8:53,1.1.1.1:53
   --dns01-recursive-nameservers-only
   ```
3. **Cloudflare/Yandex API**: Убедитесь, что Secret с API-ключом находится в том же пространстве имен, что и cert-manager (для `ClusterIssuer` — обычно в `cert-manager`).

### Диагностика ARI (ACME Renewal Information)

Если сертификат обновляется неожиданно часто (например, через 30 дней), проверьте логи контроллера:

```bash
kubectl logs -n cert-manager -l app=cert-manager | grep -i "ARI"
```
- Если в логах есть `suggestedWindow`, значит Let's Encrypt рекомендовал досрочное обновление (например, из-за технических работ или планируемого отзыва).
- **Важно:** Обновления через ARI обычно не расходуют лимит "Duplicate Certificates".

---

## Дополнительная информация

### Best Practices по диагностике

1. **Staging-first**: При любых изменениях в архитектуре DNS или Ingress сначала тестируйте на staging-сервере Let's Encrypt.
2. **Логирование**: В критических ситуациях повысьте уровень логирования контроллера до 6: `--v=6`.
3. **Мониторинг**: Используйте метрики `cert_manager_certificate_ready_status` для алертинга.
4. **Cleanup**: После успешного решения проблем cert-manager автоматически удаляет Challenge и Order. Если они "зависли", их можно удалить вручную без вреда для сертификата.

### Смотрите также

- **[Углублённые концепции ACME](./letsencrypt_concepts.md)** — CT-логи, ARI и типы аккаунтов.
- **[Практические сценарии Let's Encrypt](./letsencrypt_scenarios.md)** — полные YAML-примеры конфигураций.
- **[Cert-manager: Troubleshooting](../Administration/troubleshooting.md)** — общая диагностика контроллера (CPU, Memory, Webhook).

---

### Достоверность информации

| Предмет | Оценка | Источник |
| :--- | :--- | :--- |
| Иерархия ресурсов | **10** | Документация cert-manager |
| ARI диагностика | **9** | RFC 9773 / Release notes cert-manager 1.15+ |
| Типовые ошибки ACME | **10** | RFC 8555 / Документация Let's Encrypt |
| DNS-01 Troubleshooting | **9** | Практика эксплуатации (Cloudflare/Yandex) |
