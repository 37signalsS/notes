# Crossplane: Сравнение с Terraform

## Определения

**Crossplane** — Kubernetes-native инструмент для управления инфраструктурой через CRD с непрерывной сверкой состояния.

**Terraform** — CLI-инструмент для IaC с декларативным языком HCL и управлением состоянием через state-файлы.

## Базовые концепции: Ключевые различия

| Характеристика | Crossplane | Terraform |
| :--- | :--- | :--- |
| **Среда выполнения** | Выполняется как контроллер внутри Kubernetes | Выполняется как CLI-инструмент с любого хоста |
| **Управление состоянием** | Состояние инфраструктуры хранится в etcd Kubernetes | Требует настройки внешнего хранилища (S3, Consul, GCS) для хранения state-файла |
| **Модель выполнения** | Непрерывная сверка (reconciliation loop) — постоянно мониторит и корректирует | Выполнение по запросу (`plan`, `apply`) — требует ручного или CI/CD запуска |
| **Безопасность** | Интегрирован с RBAC и политиками Kubernetes (OPA, Kyverno) | Требует отдельных решений для управления доступом (Vault, Sentinel) |
| **Интеграция с GitOps** | Нативная (ArgoCD, Flux) — просто примени манифесты | Требует дополнительных инструментов (atlantis, terraform-cloud, scripts) |
| **Язык конфигурации** | YAML (Kubernetes CRD) | HCL (HashiCorp Configuration Language) |
| **Экосистема провайдеров** | Через Upbound Registry и community providers | Terraform Registry (наибольшая экосистема) |
| **Мультикластерность** | Через ArgoCD ApplicationSet или несколько инстансов | Через workspace и backend конфигурацию |
| **Комьюнити** | CNCF Graduated (ноябрь 2025), 100+ релизов | HashiCorp, наиболее зрелая экосистема (2014) |

## Практические сценарии выбора

### Выбирайте Crossplane когда

- Уже используете Kubernetes и GitOps (ArgoCD/Flux)
- Нужна непрерывная сверка состояния без ручных `apply`
- Требуется единый API для приложений и инфраструктуры
- Важны Kubernetes-native политики безопасности (RBAC, OPA)
- Строите внутреннюю платформу с абстракциями (Composition API)
- Команда знакома с Kubernetes и YAML

### Выбирайте Terraform когда

- Управление инфраструктурой без Kubernetes
- Требуется максимальная экосистема провайдеров (1000+)
- Команда уже имеет экспертизу в Terraform/HCL
- Нужны сложные зависимости между ресурсами
- Требуется Terraform Cloud/Enterprise для collaboration
- Работаете в средах без Kubernetes

### Гибридный подход

Многие организации используют оба инструмента:

- **Terraform**: Для начальной настройки кластера Kubernetes и базовой инфраструктуры (сеть, VPC)
- **Crossplane**: Для управления приложениями и сервисами внутри Kubernetes, ежедневные операции

Введение в Crossplane см. в [Crossplane Overview](./overview.md), интеграция с GitOps описана в [GitOps Integration](./gitops_integration.md).

## Дополнительная информация

Внешние ресурсы:

- Официальное сравнение от создателей Crossplane: [Terraform vs Crossplane 2026](https://www.crossplane.io/blog/crossplane-vs-terraform)
- Официальная документация Terraform: [terraform.io](https://www.terraform.io/)
