# Lens: Дополнительная информация

## Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.20+ | Проверено до 1.32 |
| ОЗУ | 4 GB | Минимум, рекомендуется 8 GB |
| Дисковое пространство | 500 MB | Для установки |

---

## OpenLens vs Lens Desktop

| Характеристика | OpenLens | Lens Desktop |
| :--- | :--- | :--- |
| **Лицензия** | MIT (открытая) | Commercial |
| **Расширения** | ✅ | ✅ |
| **Метрики** | ✅ | ✅ |
| **Поддержка** | Community | Commercial |
| **Обновления** | Реже | Чаще |

---

## Расширения (Extensions)

**Популярные расширения:**

- **Lens Metrics** — улучшенные метрики
- **Port Forwarder** — управление port forwarding
- **YAML Editor** — продвинутый редактор
- **GitOps** — интеграция с ArgoCD/Flux

**Установка расширений:**

1. `File > Preferences > Extensions`
2. Найдите расширение в каталоге
3. Нажмите **Install**

---

## Безопасность

1. **Защита kubeconfig:**
   - Файлы kubeconfig содержат чувствительные данные
   - Используйте файловые разрешения `600`

2. **RBAC:**
   - Lens использует права из kubeconfig
   - Ограничьте права для production-кластеров

3. **Отключение телеметрии:**

   ```
   Preferences > Application > Telemetry
   ```

---

## Ограничения

- **Ресурсоёмкость** — может потреблять значительную память
- **Не заменяет kubectl** — сложные операции требуют CLI
- **Проприетарная версия** — Lens Desktop имеет платные функции

---

## Альтернативы

| Инструмент | Тип | Преимущества |
| :--- | :--- | :--- |
| **[Octant](https://github.com/vmware-tanzu/octant)** | Open Source | Лёгкий, от VMware |
| **k9s** | TUI | Терминальный интерфейс, быстрый |
| **kubectl + vim** | CLI | Полный контроль, скриптуемость |

---

## Связанные документы

- **[kubeswitches](../kubeswitches/usage.md)** — управление контекстами
- **[Prometheus](../../../Prometheus/prometheus_api.md)** — система метрик
- **[Helm](../Helm/helm_overview.md)** — управление чартами
- **[Kubespray](../Installation/Kubespray/kubespray_install/basic_concepts.md)** — установка кластеров

---

## Репозиторий и документация

- [GitHub: OpenLens](https://github.com/MuhammedKalkan/openlens)
- [GitHub: Lens](https://github.com/lensapp/lens)
- [Официальный сайт](https://k8slens.dev/)
- [Документация](https://docs.k8slens.dev/)

---

## Ссылки на связанные файлы

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Практические сценарии](./practical_scenarios.md) — установка, настройка, использование
