# Kubespray: Развертывание HA-кластера — Основные концепции

## 1. Определения

**HA-кластер (High Availability)** — кластер Kubernetes с несколькими узлами Control Plane для устранения единой точки отказа (SPoF).

**VIP (Virtual IP)** — виртуальный IP-адрес, который служит единой точкой входа к API-серверам через механизм VRRP.

**Kubespray** — инструмент автоматизации развертывания Kubernetes на базе Ansible, поддерживающий встроенную настройку HA через Keepalived + HAProxy.

> **Основное руководство:** Подробное описание архитектуры Keepalived + HAProxy см. в [Настройка HA с kubeadm](../kudeadm/kubeadm_ha_with_keepalived_haproxy.md).

## 2. Архитектура HA через Kubespray

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

### Компоненты

| Компонент | Назначение | Порт |
| :--- | :--- | :--- |
| **Keepalived** | Управление VIP через VRRP | 112 (VRRP) |
| **HAProxy** | Балансировка трафика к API-серверам | 6443 (VIP), 6444 (local) |
| **kube-apiserver** | API Kubernetes | 6444 (локально) |

## 3. Отличия от ручного kubeadm

| Аспект | Kubespray | Ручной kubeadm |
| :--- | :--- | :--- |
| **Автоматизация** | Полная (Ansible) | Ручная настройка |
| **Keepalived/HAProxy** | Устанавливается автоматически | Ручная установка |
| **Сертификаты** | Авто-генерация с VIP | Ручное добавление SAN |
| **Время развертывания** | 15-30 минут | 1-2 часа |

## Связанные документы

- **[Развертывание HA-кластера](./kubespray_ha_deployment.md)** — инфраструктурные требования, inventory, развертывание
- **[Дополнительные темы](./kubespray_ha_advanced.md)** — тестирование отказоустойчивости, troubleshooting
- **[Kubespray: Обзор](../overview.md)** — общая информация
- **[Kubespray: Установка](../kubespray_install/basic_concepts.md)** — базовая установка
- **[HA с kubeadm](../../kubeadm/ha_keepalived_haproxy/ha_concepts.md)** — ручная настройка HA

## Внешние ресурсы

- **Kubespray Documentation:** [kubespray.io](https://kubespray.io/)
- **GitHub:** [kubernetes-sigs/kubespray](https://github.com/kubernetes-sigs/kubespray)
- **VRRP RFC:** [RFC 5798](https://datatracker.ietf.org/doc/html/rfc5798)
