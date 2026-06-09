# Kubespray: Развертывание HA-кластера

Индекс документов по развертыванию высокодоступного (HA) кластера Kubernetes с помощью Kubespray.

## Определения

**HA-кластер (High Availability)** — конфигурация Kubernetes с несколькими узлами Control Plane для обеспечения отказоустойчивости.

**Kubespray HA** — автоматизация развертывания HA-кластера через Ansible с использованием Keepalived и HAProxy.

## Основные концепции

### Документы раздела

| Документ | Описание |
| :--- | :--- |
| **[Основные концепции](./kubespray_ha_concepts.md)** | Архитектура HA, компоненты Keepalived + HAProxy, отличия от ручного kubeadm |
| **[Развертывание HA-кластера](./kubespray_ha_deployment.md)** | Требования, конфигурация inventory, переменные, процесс установки |
| **[Дополнительные темы](./kubespray_ha_advanced.md)** | Тестирование отказоустойчивости, конфигурационные файлы, troubleshooting |

## Практические сценарии

Подробное руководство по развертыванию представлено в файле [kubespray_ha_deployment.md](./kubespray_ha_deployment.md).

## Дополнительная информация

**См. также:**

- [Обзор Kubespray](../overview.md)
- [Базовая установка](../kubespray_install/basic_concepts.md)
- [Развертывание в закрытом контуре](../offline_installation/offline_definitions.md)

**Внешние ресурсы:**

- [Документация Kubespray](https://kubespray.io/)
- [GitHub проекта](https://github.com/kubernetes-sigs/kubespray)
- [VRRP RFC 5798](https://datatracker.ietf.org/doc/html/rfc5798)
