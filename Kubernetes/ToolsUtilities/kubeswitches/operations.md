# Операции kubeswitches: безопасность и ограничения

## Определения

**Операции kubeswitches** — безопасность, ограничения и альтернативные инструменты для управления контекстами Kubernetes.

> **Навигация:** [Главная kubeswitches](./index.md) | [Использование](./usage.md)

---

## Practical Scenarios

### Безопасность

#### Защита файлов kubeconfig

```bash
chmod 600 ~/.kube/contexts/*/config
chmod 700 ~/.kube/contexts
```

#### Изоляция production-контекстов

Рассмотрите возможность хранения production kubeconfig на зашифрованных носителях или в менеджерах секретов.

---

## Additional Information

### Ограничения

- **Не управляет контекстами внутри одного файла** — требует отдельной директории на кластер
- **Копирование файлов** — может быть медленнее чем переключение через `kubectl config use-context`
- **Отсутствие синхронизации** — изменения в облачных kubeconfig не синхронизируются автоматически

---

### Альтернативы

| Инструмент | Описание |
| :--- | :--- |
| **[kubectx](https://github.com/ahmetb/kubectx)** | Быстрое переключение между контекстами в одном файле |
| **kubectl config** | Встроенные команды управления контекстами |
| **[ctx](https://github.com/ahmetb/kubectx)** | Обёртка над kubectl config с автодополнением |

---

### Связанные документы

- **[kubectl](../Base/kubectl.md)** — основы работы с kubectl
- **[kubeconfig](../Base/kubeconfig.md)** — структура и использование kubeconfig
- **[Lens](../lens/definitions_and_concepts.md)** — GUI для управления несколькими кластерами

### Репозиторий и документация

> ⚠️ **Примечание:** Проект kubeswitches может быть менее известен. Проверьте актуальность репозитория перед использованием.

- [GitHub: поиск kubeswitches](https://github.com/search?q=kubeswitches)
- Альтернатива: **[kubectx](https://github.com/ahmetb/kubectx)** — более популярный инструмент
