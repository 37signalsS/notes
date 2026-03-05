# Let's Encrypt: Дополнительные темы

## 1. Диагностика

```bash
# Статус Certificate
kubectl get certificate example-com -o wide

# Детали Order
kubectl get order -l cert-manager.io/certificate-name=example-com

# Детали Challenge
kubectl get challenge -l cert-manager.io/certificate-name=example-com

# Логи cert-manager
kubectl logs -n cert-manager -l app=cert-manager | grep -i acme
```

## 2. Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `403 Forbidden` | Неправильный API-ключ DNS | Проверить права доступа |
| `Connection timed out` | HTTP-01 недоступен извне | Проверить Ingress, firewall |
| `rateLimitReached` | Превышен лимит Let's Encrypt | Использовать staging, подождать |
| `DNS propagation` | TXT-запись не видна | Подождать 1-5 минут |

## 3. Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| ACME протокол | **10** | RFC 8555, Let's Encrypt документация |
| HTTP-01 solver | **10** | Стандартный паттерн cert-manager |
| DNS-01 solver | **10** | Подтверждено для wildcard |
| Staging окружение | **10** | Официальное тестовое окружение LE |

## 4. Best Practices

1. **Всегда используйте staging** для первичной настройки
2. **Настройте уведомления** на email о продлении
3. **Мониторьте статус** Certificate через Prometheus/Grafana
4. **Избегайте лимитов** — кэшируйте заказы при разработке

## Связанные документы

- **[Основные концепции](./letsencrypt_concepts.md)** — определения, ACME solvers, окружения
- **[Практические сценарии](./letsencrypt_scenarios.md)** — ClusterIssuer, HTTP-01, DNS-01, wildcard
- **[cert_manager](../cert_manager_overview.md)** — обзор cert-manager
- **[private_ca](../private_ca.md)** — частные CA для внутренних доменов
