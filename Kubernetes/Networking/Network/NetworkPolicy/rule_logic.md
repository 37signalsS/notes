# NetworkPolicy: Логика Правил

## Логика Правил: "И" и "ИЛИ"

Понимание логических операторов критически важно:

* **Логическое "ИЛИ"**: Элементы в списках `ingress`, `egress`, `from`, `to` объединяются по "ИЛИ". Трафик разрешается, если он соответствует **любому** правилу в списке.
* **Логическое "И"**: Поля внутри одного элемента (`podSelector`, `namespaceSelector`, `ports`) объединяются по "И". Трафик должен соответствовать **всем** условиям внутри правила.

## Примеры различной логики

### Пример 1: Логическое "ИЛИ" в списке `from`

```yaml
ingress:
- from:
  - podSelector:
      matchLabels:
        app: indexer
  - podSelector:
      matchLabels:
        app: opadmin
  ports:
  - port: 5432
```

**Результат:** Разрешён трафик от подов с меткой `app: indexer` **ИЛИ** `app: opadmin` на порт 5432.

### Пример 2: Логическое "И" внутри одного элемента

```yaml
ingress:
- from:
  - namespaceSelector:
      matchLabels:
        env: default
    podSelector:
      matchLabels:
        role: opadmin
  ports:
  - port: 5432
```

**Результат:** Разрешён трафик только от подов с меткой `role: opadmin`, находящихся в namespace с меткой `env: default`. Оба условия должны выполняться **одновременно**.

### Пример 3: Разные порты для разных селекторов

```yaml
ingress:
- from:
  - podSelector:
      matchLabels:
        app: indexer
  ports:
  - port: 443
- from:
  - podSelector:
      matchLabels:
        app: admin
  ports:
  - port: 80
```

**Результат:**

* Для `indexer`: разрешён только порт 443
* Для `admin`: разрешён только порт 80

### Пример 4: Комбинация namespaceSelector и podSelector

```yaml
# Вариант А: И (один элемент массива)
ingress:
- from:
  - namespaceSelector:
      matchLabels:
        env: default
    podSelector:
      matchLabels:
        role: opadmin

# Вариант Б: ИЛИ (два элемента массива)
ingress:
- from:
  - namespaceSelector:
      matchLabels:
        env: default
  - podSelector:
      matchLabels:
        role: opadmin
```

**Результат:**

* **Вариант А (И):** Поды `opadmin` из namespace `default`
* **Вариант Б (ИЛИ):** Любые поды из namespace `default` **ИЛИ** любые поды с меткой `opadmin` из текущего namespace
