# Миграция с Ingress на Gateway API

**ingress2gateway** — официальный инструмент CLI для автоматического преобразования манифестов Kubernetes Ingress в ресурсы Gateway API.

## Навигация

### Основы миграции

- **[Основы миграции](./migration_basics.md)** — выбор реализации, параллельный запуск, ingress2gateway
- **[Миграция TLS и маршрутизации](./migration_tls_and_routing.md)** — сценарии TLS, ручная конвертация
- **[Тестирование и перенос трафика](./migration_testing.md)** — план тестирования, мониторинг

---

## Быстрый старт

```bash
# Установка ingress2gateway
curl -Lo ingress2gateway https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.0/ingress2gateway-linux-amd64
chmod +x ingress2gateway
sudo mv ingress2gateway /usr/local/bin/

# Конвертация и применение
ingress2gateway convert --namespace=my-app | kubectl apply -f -
```

---

## Временная шкала

| Дата | Событие |
| :--- | :--- |
| **Март 2026** | Прекращение поддержки Ingress NGINX |
| **Q1 2026** | Рекомендуется завершить миграцию в production |

---

## Связанные документы

- **[Определения Gateway API](./definitions.md)** — концепции и ролевая модель
- **[Ресурсы (CRD)](./resources.md)** — GatewayClass, Gateway, HTTPRoute
- **[Базовые сценарии](./practical_basic.md)** — основы создания ресурсов
- **[Ingress: Обзор](../Ingress/overview.md)** — текущий стандарт
