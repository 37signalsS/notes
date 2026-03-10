# RKE: Основные концепции

## 1. Определения

**RKE (Rancher Kubernetes Engine)** — дистрибутив Kubernetes от Rancher Labs, предназначенный для развертывания production-кластеров на bare-metal и виртуальных машинах.

**Rancher** — платформа управления Kubernetes, предоставляющая веб-UI для развертывания, мониторинга и управления кластерами (включая RKE).

**kubeconfig** — YAML-файл с конфигурацией доступа к Kubernetes API (контексты, пользователи, кластеры).

> **Примечание:** RKE2 (Rancher Government Kubernetes) — следующая версия RKE с улучшенной безопасностью. Не путать с RKE1.

## 2. Основные концепции

### Отличия RKE от kubeadm

| Аспект | kubeadm | RKE |
| :--- | :--- | :--- |
| **Установка** | Команды `kubeadm init/join` на узлах | Через `cluster.yml` + `./rke up` |
| **Конфигурация** | Ручная на каждом узле | Декларативная (YAML) |
| **Управление** | kubectl + kubeadm | Rancher UI + kubectl |
| **kubectl на узлах** | Устанавливается автоматически | Не устанавливается (только через Rancher) |
| **HA** | Ручная настройка | Встроенная поддержка |

### Архитектура доступа

```
┌─────────────┐      ┌──────────────┐      ┌─────────────────┐
│   kubectl   │ ───► │  kubeconfig  │ ───► │  RKE API Server │
│  (локально) │      │ (~/.kube/)   │      │   (порт 6443)   │
└─────────────┘      └──────────────┘      └─────────────────┘
                                                    │
                                  ┌─────────────────┼─────────────────┐
                                  │                 │                 │
                         ┌────────▼───────┐ ┌──────▼──────┐ ┌───────▼──────┐
                         │  Control Plane │ │ Worker Node │ │ Worker Node  │
                         │    (etcd+API)  │ │             │ │              │
                         └────────────────┘ └─────────────┘ └──────────────┘
```

## 3. Сравнение методов управления

| Метод | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **Rancher UI** | Визуальный интерфейс, мониторинг | Требует ресурсов на Rancher |
| **kubectl** | Стандартный инструмент, скрипты | Только CLI |
| **RKE CLI** | Полная автоматизация | Меньше возможностей чем UI |
| **Terraform RKE provider** | Infrastructure as Code | Сложнее настройка |

## Связанные документы

- **[RKE: Установка kubectl и настройка доступа](./rke_kubectl_setup.md)** — установка kubectl, получение kubeconfig
- **[RKE: Управление и troubleshooting](./rke_management_scenarios.md)** — практические сценарии управления
- **[kubeadm: Быстрый старт](../kubeadm/ha_keepalived_haproxy/index.md)** — альтернативный метод установки
- **[kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md)** — детали конфигурации
- **[RKE2 документация](https://docs.rke2.io/)** — следующая версия RKE

## Внешние ресурсы

- **Rancher Documentation:** [ranchermanager.docs.rancher.com](https://ranchermanager.docs.rancher.com/)
- **RKE GitHub:** [github.com/rancher/rke](https://github.com/rancher/rke)
- **kubectl Reference:** [kubernetes.io/docs/reference/kubectl/](https://kubernetes.io/docs/reference/kubectl/)
