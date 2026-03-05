# Интеграция Cert-manager с Gateway API: Дополнительная информация

## Особенности работы с hostname

**Проблема:** При указании `hostname` в Gateway cert-manager может некорректно определять домены для сертификата.

**Решения:**

1. Создать `Certificate` вручную перед Gateway
2. Дождаться создания Secret
3. Применить Gateway с ссылкой на Secret

---

## Диагностика

```bash
# Статус Gateway
kubectl get gateway -n default

# Детали Gateway
kubectl describe gateway example-gateway -n default

# Статус Certificate
kubectl get certificate -n default

# Логи cert-manager
kubectl logs -n cert-manager -l app=cert-manager | grep -i gateway
```

---

## Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Gateway API not enabled` | Флаг не указан | Пересоздать с `--enable-gateway-api=true` |
| `CertificateRef not found` | Secret не создан | Проверить статус Certificate |
| `hostname конфликт` | cert-manager не определяет домен | Создать Certificate вручную |
| `CRD missing` | Gateway API CRD не установлены | Установить CRD до cert-manager |

---

## Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Gateway API интеграция | **9** | Подтверждено в cert-manager 1.13+ |
| Несколько слушателей | **9** | Работает в Traefik, Envoy Gateway |
| TLS Passthrough | **8** | Зависит от реализации Gateway Controller |
| Wildcard сертификаты | **10** | Стандартный ACME DNS-01 |

---

## Ссылки

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Практические сценарии](./practical_scenarios.md) — настройка и использование
