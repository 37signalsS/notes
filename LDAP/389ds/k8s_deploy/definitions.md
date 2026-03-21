# 389DS в Kubernetes: Определения

## Определения

**StatefulSet** — контроллер Kubernetes для stateful-приложений с уникальными идентификаторами подов и персистентным хранилищем.

**Headless Service** — сервис без ClusterIP для прямого DNS-discovery подов StatefulSet.

**389DS (389 Directory Server)** — открытый LDAP-сервер для управления каталогами пользователей, групп и ресурсов.

**DIT (Directory Information Tree)** — иерархическая структура записей в LDAP-каталоге.

---

## Связанные документы

- **[Основные концепции](./basic_concepts.md)** — архитектура развёртывания, требования
- **[Практические сценарии](./practical_scenarios.md)** — StatefulSet, сервисы, инициализация
- **[Дополнительная информация](./additional_info.md)** — troubleshooting, мониторинг, best practices
