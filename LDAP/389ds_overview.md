# 389 Directory Server (389DS) — Индекс

> **Данный файл декомпозирован.** Актуальная информация разделена на тематические заметки.

## Основная документация

| Файл | Описание |
| :--- | :--- |
| [overview.md](./389ds/overview.md) | Определения, архитектура, терминология, требования |
| [docker.md](./389ds/docker.md) | Развёртывание в Docker, переменные окружения |
| [replication.md](./389ds/replication.md) | Multi-Master репликация, troubleshooting |
| [kubernetes.md](./389ds/kubernetes.md) | StatefulSet, Services, Job для инициализации |
| [plugins.md](./389ds/plugins.md) | RetroChangelog, MemberOf, DNA, ACI |
| [aci.md](./389ds/aci.md) | Access Control Instructions, примеры, best practices |

## Быстрый старт

1. **Тестирование:** [Docker развёртывание](./389ds/docker.md)
2. **Production HA:** [Настройка репликации](./389ds/replication.md)
3. **Kubernetes:** [StatefulSet развёртывание](./389ds/kubernetes.md)

## Связанные темы

* [LDAP основы](../Linux/SystemAdministration/users_management.md#LDAP-Lightweight-Directory-Access-Protocol)
* [OpenLDAP в Kubernetes](./openldap_kubernetes.md) — сравнение с 389DS
* [SSSD для LDAP-аутентификации](../../Linux/SystemAdministration/Users/LDAP_SSSD/index.md)
* [Kubernetes основы](../../Kubernetes/kubernetes_overview.md)

## Внешние ресурсы

* [Официальная документация](https://www.port389.org/docs/389ds/)
* [GitHub репозиторий](https://github.com/389ds/389-ds-base)
* [Контейнеры quay.io](https://quay.io/repository/389ds/ds-container)
