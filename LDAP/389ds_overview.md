# 389 Directory Server (389DS)

> **Данный файл декомпозирован.** Актуальная информация разделена на тематические заметки.

## Тематические заметки

* [Определения и требования](./389ds/overview.md) — основные определения, требования к ресурсам, безопасность
* [Docker развертывание](./389ds/docker.md) — запуск в Docker, переменные окружения, структура данных
* [Настройка репликации](./389ds/replication.md) — Multi-Master репликация между двумя узлами
* [Развертывание в Kubernetes](./389ds/kubernetes.md) — StatefulSet, Services, Jobs, TLS
* [Плагины 389DS](./389ds/plugins.md) — RetroChangeLog, MemberOf
* [Управление доступом (ACI)](./389ds/aci.md) — Access Control Instructions

## Связанные темы

* [LDAP](../Linux/SystemAdministration/users_management.md#LDAP-Lightweight-Directory-Access-Protocol) — основы протокола LDAP
* [OpenLDAP в Kubernetes](openldap_kubernetes.md) — развёртывание и эксплуатация OpenLDAP в Kubernetes
* [Kubernetes](../Kubernetes/kubernetes_overview.md) — оркестрация контейнеров
* [Helm](../Kubernetes/Installation/Kubespray/overview.md) — менеджер пакетов для Kubernetes
