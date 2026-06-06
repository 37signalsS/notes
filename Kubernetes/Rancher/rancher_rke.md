# RKE в Rancher

> **Примечание:** Основная документация по установке RKE находится в [Kubernetes/Installation/RKE/index.md](../Installation/RKE/index.md). Данный документ описывает специфику работы RKE в экосистеме Rancher.

## Определения

**RKE (Rancher Kubernetes Engine)** — сертифицированный дистрибутив Kubernetes от Rancher Labs. Подробное описание дистрибутива и методов его установки через CLI доступно в [основном разделе RKE](../Installation/RKE/index.md).

**Cattle Cluster Agent** — специализированный компонент, разворачиваемый внутри RKE-кластера для обеспечения связи с Rancher Server.

## Базовые концепции

### Архитектура связи через Cattle Agent

В отличие от традиционных методов управления, где управляющий узел подключается к кластеру, Rancher использует модель "обратного подключения".

```
┌─────────────────┐         ┌──────────────────────┐
│  Rancher Server │ ◄─────► │  Cattle Cluster Agent │
│   (веб-интерфейс)│         │   (в RKE-кластере)    │
└─────────────────┘         └──────────────────────┘
                                     │
                              ┌──────┴──────┐
                              │             │
                     ┌────────▼────┐ ┌──────▼──────┐
                     │ Control Plane│ │ Worker Nodes│
                     └──────────────┘ └─────────────┘
```

**Особенности взаимодействия:**

* **Исходящее соединение:** Агент сам инициирует соединение с Rancher Server по HTTPS (порт 443). Это позволяет управлять кластерами за NAT или Firewall без проброса портов внутрь кластера.
* **Автономность:** Если связь с Rancher Server прервется, кластер продолжит работу. Rancher нужен только для управления и мониторинга.
* **Безопасность:** Весь трафик шифруется TLS.

## Практические сценарии

### Создание кластера RKE через интерфейс Rancher

Процесс визуального развертывания через Rancher UI:

1. **Выбор типа:** `Cluster Management` → `Create` → `RKE1` (или RKE2/K3s для современных инсталляций).
2. **Конфигурация узлов:** Определение ролей (etcd, Control Plane, Worker).
3. **Параметры сети:** Выбор CNI-плагина (Flannel, Calico, Cilium).
4. **Регистрация узлов:** Выполнение сгенерированной команды `docker run ... rancher/rancher-agent` на целевых хостах.

### Развертывание приложения (Workload)

1. **Выбор контекста:** Перейти в нужный `Project` и `Namespace`.
2. **Создание Workload:** `Workloads` → `Deployments` → `Create`.
   * Указать имя и образ контейнера.
   * Настроить Port Mapping для внешнего доступа.
3. **Настройка Ingress:** `Service Discovery` → `Ingresses` → `Create`.
   * Указать Hostname и путь (Path).
   * Выбрать целевой сервис, созданный на предыдущем шаге.

## Дополнительная информация

Для работы с RKE вне интерфейса Rancher (через CLI или Terraform) используйте следующие ресурсы:

* [Установка RKE через CLI](../Installation/RKE/rke_management_scenarios.md) — для Infrastructure as Code.
* [Настройка доступа через kubectl](../Installation/RKE/rke_kubectl_setup.md) — для локальной работы с API.
* [rancher_overview](./rancher_overview.md) — общие принципы работы платформы Rancher.

**Внешние ресурсы:**

* [Официальная документация Rancher](https://ranchermanager.docs.rancher.com/)
* [RKE Documentation](https://rke.docs.rancher.com/)
