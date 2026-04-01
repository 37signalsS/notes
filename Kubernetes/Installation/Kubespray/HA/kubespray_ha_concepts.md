# Kubespray: Развертывание HA-кластера — Основные концепции

## Definitions

**HA-кластер (High Availability)** — кластер Kubernetes с несколькими узлами Control Plane для устранения единой точки отказа (SPoF).

**VIP (Virtual IP)** — виртуальный IP-адрес, который служит единой точкой входа к API-серверам через механизм VRRP.

**Kubespray** — инструмент автоматизации развертывания Kubernetes на базе Ansible, поддерживающий встроенную настройку HA через Keepalived + HAProxy.

## Basic Concepts

### Архитектура HA через Kubespray

Kubespray автоматизирует настройку HA следующим образом:

```
                    ┌─────────────────┐
                    │      VIP        │
                    │  192.168.1.100  │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───────┐ ┌───▼────────┐ ┌───▼────────┐
     │   Master-1     │ │  Master-2  │ │  Master-3  │
     │  Keepalived    │ │ Keepalived │ │ Keepalived │
     │    MASTER      │ │  BACKUP    │ │  BACKUP    │
     │   HAProxy:6443 │ │HAProxy:6443│ │HAProxy:6443│
     │ apiserver:6444 │ │apiserver:6444│ │apiserver:6444│
     └────────────────┘ └────────────┘ └────────────┘
```

#### Компоненты

| Компонент | Назначение | Порт |
| :--- | :--- | :--- |
| **Keepalived** | Управление VIP через VRRP | 112 (VRRP) |
| **HAProxy** | Балансировка трафика к API-серверам | 6443 (VIP), 6444 (local) |
| **kube-apiserver** | API Kubernetes | 6444 (локально) |

#### Отличия от ручного kubeadm

| Аспект | Kubespray | Ручной kubeadm |
| :--- | :--- | :--- |
| **Автоматизация** | Полная (Ansible) | Ручная настройка |
| **Keepalived/HAProxy** | Устанавливается автоматически | Ручная установка |
| **Сертификаты** | Авто-генерация с VIP | Ручное добавление SAN |
| **Время развертывания** | 15-30 минут | 1-2 часа |

Подробное описание архитектуры Keepalived + HAProxy см. в [ручной настройке HA с kubeadm](../../kubeadm/ha_keepalived_haproxy/ha_concepts.md).

## Practical Scenarios

Базовая установка Kubespray описана в [руководстве по установке](../kubespray_install/basic_concepts.md). Развертывание HA-кластера — в [практическом руководстве](./kubespray_ha_deployment.md).

## Additional Information

**См. также:** [развертывание в закрытом контуре](../offline_installation/offline_definitions.md).

**Внешние ресурсы:** [документация Kubespray](https://kubespray.io/), [GitHub](https://github.com/kubernetes-sigs/kubespray), [VRRP RFC 5798](https://datatracker.ietf.org/doc/html/rfc5798).
