---
name: react-developer
description: Expert knowledge in React development, hooks, state management, and modern React patterns
---

# React Developer Skill

## Core React Concepts

### Components and JSX
- Functional components with hooks
- Class components (legacy support)
- JSX syntax and best practices
- Props and prop validation with PropTypes/TypeScript

### React Hooks Mastery
- **useState**: State management in functional components
- **useEffect**: Side effects and lifecycle management
- **useContext**: Context API for state sharing
- **useReducer**: Complex state management
- **useMemo**: Performance optimization with memoization
- **useCallback**: Function memoization
- **useRef**: DOM access and persistent values
- **Custom Hooks**: Reusable stateful logic

### State Management Patterns
- **Local State**: useState, useReducer
- **Context API**: useContext for global state
- **Redux**: State management with Redux Toolkit
- **Zustand**: Lightweight state management
- **Recoil**: Facebook's state management library
- **SWR/React Query**: Server state management

### Performance Optimization
- React.memo for component memoization
- useMemo and useCallback for expensive computations
- Code splitting with React.lazy and Suspense
- Virtual scrolling for large lists
- Bundle size optimization

### Modern React Patterns
- **Compound Components**: Flexible component composition
- **Render Props**: Sharing component logic
- **Higher-Order Components (HOCs)**: Component enhancement
- **Custom Hooks Pattern**: Reusable stateful logic
- **State Reducer Pattern**: Complex state updates
- **Control Props Pattern**: External component control

### Styling Solutions
- **CSS Modules**: Scoped CSS
- **Styled Components**: CSS-in-JS
- **Emotion**: High-performance CSS-in-JS
- **Tailwind CSS**: Utility-first CSS
- **CSS-in-JS best practices**

### Testing Strategies
- **Jest**: Testing framework
- **React Testing Library**: Component testing
- **Enzyme**: Component testing (legacy)
- **Cypress**: End-to-end testing
- **Storybook**: Component development and testing

### React Ecosystem Tools
- **Create React App**: Quick start setup
- **Vite**: Fast build tool
- **Next.js**: Full-stack React framework
- **Gatsby**: Static site generator
- **Remix**: Full-stack web framework

### Best Practices
1. **Component Design**: Single responsibility principle
2. **Prop Drilling**: Avoid with context or state management
3. **Side Effects**: Proper useEffect dependency management
4. **Key Props**: Correct usage in lists
5. **Conditional Rendering**: Best practices
6. **Error Boundaries**: Graceful error handling
7. **Accessibility**: ARIA attributes and semantic HTML

### Common Pitfalls and Solutions
- **Stale Closures**: Proper dependency arrays
- **Infinite Renders**: Incorrect useEffect dependencies
- **Memory Leaks**: Cleanup functions in useEffect
- **Prop Drilling**: Use context or state management
- **Unnecessary Re-renders**: Memoization strategies

### Migration and Upgrade Guides
- **React Class to Functional**: Migration strategies
- **React 18 Features**: Concurrent features, automatic batching
- **Strict Mode**: Development best practices

## Code Examples

### Custom Hook Example
```javascript
import { useState, useEffect } from 'react';

function useFetch(url) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const response = await fetch(url);
        const data = await response.json();
        setData(data);
      } catch (err) {
        setError(err);
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, [url]);

  return { data, loading, error };
}
```

### Performance Optimization Example
```javascript
import React, { memo, useMemo, useCallback } from 'react';

const ExpensiveComponent = memo(({ items, onItemClick }) => {
  const processedItems = useMemo(() => {
    return items.map(item => ({
      ...item,
      processed: true,
      value: item.value * 2
    }));
  }, [items]);

  const handleClick = useCallback((item) => {
    onItemClick(item);
  }, [onItemClick]);

  return (
    <div>
      {processedItems.map(item => (
        <div key={item.id} onClick={() => handleClick(item)}>
          {item.value}
        </div>
      ))}
    </div>
  );
});
```

When working with React projects, always consider:
- Component reusability and composition
- Performance implications of state changes
- Accessibility requirements
- Testing strategies
- Bundle size impact
- SEO considerations for server-rendered apps