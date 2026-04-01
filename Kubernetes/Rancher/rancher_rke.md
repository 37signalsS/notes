# RKE в Rancher

> **Примечание:** Полная документация RKE перемещена в [Kubernetes/Installation/RKE/index.md](../Installation/RKE/index.md). Данный документ содержит только специфичные для Rancher дополнения.

## Определения

**RKE (Rancher Kubernetes Engine)** — дистрибутив Kubernetes от Rancher Labs для развертывания production-кластеров. Подробная документация доступна в [основном файле RKE](../Installation/RKE/index.md).

**Cattle Cluster Agent** — агент, запускаемый на узлах RKE-кластера, который подключается к Rancher Server и передаёт информацию о состоянии кластера.

## Базовые концепции

### Архитектура взаимодействия

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

**Важно:** Rancher Server не «лезет» напрямую в кластер. Cattle Cluster Agent сам устанавливает соединение с Rancher и передаёт данные о кластере.

## Практические сценарии

### Создание кластера RKE через Rancher UI

1. Перейти в `Global` → `Clusters` → `Add Cluster`
2. Выбрать `Create a new Kubernetes cluster using Rancher Kubernetes Engine`
3. Настроить кластер:
   - Имя и описание
   - Версия Kubernetes и тип дистрибутива (RKE2/K3s)
   - Network Provider (Flannel/Calico/Cilium)
   - Cloud Provider (`None` для bare-metal)
4. Добавить узлы с ролями:
   - **etcd** — 3 или 5 узлов для кворума
   - **Control Plane** — 2 или 3 узла для HA
   - **Worker** — рабочие узлы для подов приложений
5. Запустить `rancher-agent` на каждом узле (команда генерируется в Rancher UI)
6. Дождаться статуса `Active`

### Развертывание приложения через Rancher UI

1. Выбрать `Project` и `Namespace`
2. **Deployment:** `Workloads` → `Deployments` → `Create`
   - Имя deployment
   - Образ контейнера
   - Port Mapping (NodePort для внешнего доступа)
3. **Ingress:** `Load Balancing` → `Ingresses` → `Create`
   - Hostname (например, `www.example.local`)
   - Path (например, `/`)
   - Target Service (выбрать созданный service)

## Дополнительная информация

**См. также:** [RKE: Основные концепции](../Installation/RKE/rke_concepts.md), [RKE: Установка kubectl и настройка доступа](../Installation/RKE/rke_kubectl_setup.md), [Rancher: Обзор](./rancher_overview.md).
