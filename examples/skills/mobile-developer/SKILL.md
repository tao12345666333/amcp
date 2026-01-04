---
name: mobile-developer
description: Expert knowledge in mobile app development for iOS, Android, and cross-platform solutions
---

# Mobile Developer Skill

## Platform-Specific Development

### iOS Development (Swift/Objective-C)

#### Swift Fundamentals
- **Swift Syntax**: Modern, type-safe language features
- **SwiftUI**: Declarative UI framework
- **UIKit**: Imperative UI framework (legacy)
- **Combine**: Reactive programming framework
- **Core Data**: Local data persistence
- **Core Animation**: Graphics and animations

#### iOS Architecture Patterns
- **MVC**: Traditional Model-View-Controller
- **MVVM**: Model-View-ViewModel with data binding
- **VIPER**: Clean Architecture for iOS
- **Coordinator Pattern**: Navigation flow management

#### iOS Frameworks
- **Foundation**: Basic data types and utilities
- **Core Foundation**: C-based utilities
- **AVFoundation**: Audio/video processing
- **Core Location**: GPS and location services
- **Core Bluetooth**: Bluetooth connectivity
- **CloudKit**: Cloud data synchronization

### Android Development (Kotlin/Java)

#### Kotlin Fundamentals
- **Kotlin Syntax**: Concise, expressive language
- **Coroutines**: Asynchronous programming
- **Jetpack Compose**: Modern declarative UI
- **View System**: Traditional UI framework
- **Room**: Local database abstraction
- **DataStore**: Key-value data storage

#### Android Architecture Components
- **ViewModel**: UI-related data storage
- **LiveData**: Observable data holder
- **Repository**: Data repository pattern
- **Navigation Component**: In-app navigation
- **WorkManager**: Background task management

#### Android Frameworks
- **Android SDK**: Core development platform
- **AndroidX**: Modern Android support library
- **Play Services**: Google services integration
- **Firebase**: Mobile app development platform

## Cross-Platform Development

### React Native
- **JavaScript/TypeScript**: Web technologies for mobile
- **React Concepts**: Components, hooks, state management
- **Native Modules**: Bridging native code
- **Navigation**: React Navigation library
- **State Management**: Redux, MobX, Zustand

### Flutter
- **Dart Language**: Type-safe, object-oriented language
- **Widget System**: Declarative UI building
- **State Management**: Provider, BLoC, Riverpod
- **Packages**: Flutter ecosystem and pub.dev
- **Platform Integration**: Platform channels and plugins

### Xamarin
- **C#/.NET**: Microsoft ecosystem
- **Xamarin.Forms**: Cross-platform UI framework
- **Xamarin.Native**: Platform-specific development
- **MAUI**: Evolution of Xamarin.Forms

## Mobile App Architecture

### Clean Architecture Principles
1. **Presentation Layer**: UI and view controllers
2. **Domain Layer**: Business logic and entities
3. **Data Layer**: Repository pattern and data sources

### Common Design Patterns
- **Repository Pattern**: Data access abstraction
- **Factory Pattern**: Object creation
- **Observer Pattern**: Event handling
- **Singleton Pattern**: Global state management
- **Strategy Pattern**: Algorithm selection

## Mobile-Specific Considerations

### Performance Optimization
- **Memory Management**: Avoid leaks and optimize usage
- **Battery Life**: Efficient resource utilization
- **Network Usage**: Minimize data transfer
- **UI Responsiveness**: 60fps target for smooth animations
- **App Size**: Reduce binary and resource size

### User Experience
- **Touch Interactions**: Gesture recognition and handling
- **Screen Adaptation**: Different screen sizes and orientations
- **Accessibility**: VoiceOver, TalkBack, and assistive technologies
- **Platform Guidelines**: iOS Human Interface, Android Material Design

### Security Best Practices
- **Data Encryption**: Protect sensitive information
- **Network Security**: HTTPS, certificate pinning
- **Authentication**: Biometric, OAuth, JWT
- **Code Obfuscation**: Protect intellectual property
- **Root/Jailbreak Detection**: Security checks

## Development Tools and Workflow

### Build Systems
- **iOS**: Xcode, Swift Package Manager
- **Android**: Android Studio, Gradle
- **Cross-Platform**: Metro (React Native), Flutter CLI

### Testing Strategies
- **Unit Tests**: Business logic validation
- **Integration Tests**: Component interaction
- **UI Tests**: User interface automation
- **Performance Tests**: Memory, CPU, battery usage

### Continuous Integration/Deployment
- **CI/CD Pipelines**: Automated build and testing
- **App Store Deployment**: Apple App Store, Google Play Store
- **Beta Testing**: TestFlight, Google Play Console beta

## Code Examples

### React Native Component
```javascript
import React, { useState, useEffect } from 'react';
import { View, Text, TextInput, Button, StyleSheet } from 'react-native';
import { useNavigation } from '@react-navigation/native';

const LoginForm = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const navigation = useNavigation();

  const handleLogin = async () => {
    setLoading(true);
    try {
      // API call for authentication
      await loginAPI(email, password);
      navigation.navigate('Home');
    } catch (error) {
      console.error('Login failed:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Login</Text>
      <TextInput
        style={styles.input}
        placeholder="Email"
        value={email}
        onChangeText={setEmail}
        keyboardType="email-address"
        autoCapitalize="none"
      />
      <TextInput
        style={styles.input}
        placeholder="Password"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
      />
      <Button
        title={loading ? "Logging in..." : "Login"}
        onPress={handleLogin}
        disabled={loading}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 20,
    justifyContent: 'center',
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    textAlign: 'center',
    marginBottom: 20,
  },
  input: {
    height: 40,
    borderColor: 'gray',
    borderWidth: 1,
    marginBottom: 10,
    paddingHorizontal: 10,
  },
});
```

### SwiftUI View
```swift
import SwiftUI

struct LoginView: View {
    @State private var email = ""
    @State private var password = ""
    @State private var showingAlert = false
    @State private var alertMessage = ""
    
    var body: some View {
        VStack(spacing: 20) {
            Text("Login")
                .font(.largeTitle)
                .fontWeight(.bold)
            
            TextField("Email", text: $email)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .keyboardType(.emailAddress)
                .autocapitalization(.none)
            
            SecureField("Password", text: $password)
                .textFieldStyle(RoundedBorderTextFieldStyle())
            
            Button(action: login) {
                Text("Login")
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(Color.blue)
                    .foregroundColor(.white)
                    .cornerRadius(10)
            }
            .disabled(email.isEmpty || password.isEmpty)
        }
        .padding()
        .alert(isPresented: $showingAlert) {
            Alert(title: Text("Error"), message: Text(alertMessage))
        }
    }
    
    private func login() {
        // Authentication logic
        guard !email.isEmpty, !password.isEmpty else {
            alertMessage = "Please fill in all fields"
            showingAlert = true
            return
        }
        
        // API call for authentication
        AuthAPI.login(email: email, password: password) { result in
            switch result {
            case .success:
                // Navigate to home screen
                break
            case .failure(let error):
                alertMessage = error.localizedDescription
                showingAlert = true
            }
        }
    }
}
```

### Flutter Widget
```dart
import 'package:flutter/material.dart';

class LoginForm extends StatefulWidget {
  @override
  _LoginFormState createState() => _LoginFormState();
}

class _LoginFormState extends State<LoginForm> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _isLoading = false;

  Future<void> _login() async {
    if (_formKey.currentState!.validate()) {
      setState(() => _isLoading = true);
      
      try {
        await AuthAPI.login(
          email: _emailController.text,
          password: _passwordController.text,
        );
        
        Navigator.pushReplacementNamed(context, '/home');
      } catch (e) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Login failed: ${e.toString()}')),
        );
      } finally {
        setState(() => _isLoading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Login')),
      body: Padding(
        padding: EdgeInsets.all(16.0),
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              TextFormField(
                controller: _emailController,
                decoration: InputDecoration(labelText: 'Email'),
                keyboardType: TextInputType.emailAddress,
                validator: (value) {
                  if (value == null || value.isEmpty) {
                    return 'Please enter your email';
                  }
                  return null;
                },
              ),
              SizedBox(height: 16),
              TextFormField(
                controller: _passwordController,
                decoration: InputDecoration(labelText: 'Password'),
                obscureText: true,
                validator: (value) {
                  if (value == null || value.isEmpty) {
                    return 'Please enter your password';
                  }
                  return null;
                },
              ),
              SizedBox(height: 24),
              _isLoading
                  ? CircularProgressIndicator()
                  : ElevatedButton(
                      onPressed: _login,
                      child: Text('Login'),
                      style: ElevatedButton.styleFrom(
                        minimumSize: Size(double.infinity, 48),
                      ),
                    ),
            ],
          ),
        ),
      ),
    );
  }
}
```

## Best Practices

### Code Quality
1. **Architecture**: Follow clean architecture principles
2. **Design Patterns**: Use appropriate patterns for problems
3. **Code Reusability**: Create modular, reusable components
4. **Documentation**: Maintain clear code documentation

### Performance
1. **Memory Management**: Profile and optimize memory usage
2. **Network Optimization**: Implement caching and efficient data transfer
3. **UI Performance**: Maintain 60fps animations
4. **Battery Optimization**: Minimize resource consumption

### Security
1. **Data Protection**: Encrypt sensitive data
2. **Network Security**: Use HTTPS and certificate pinning
3. **Authentication**: Implement secure authentication flows
4. **Code Security**: Obfuscate and protect code

When developing mobile applications, always consider:
- Platform-specific design guidelines
- Performance constraints and optimization
- User experience and accessibility
- Security and data privacy
- App store guidelines and approval processes
- Device fragmentation and compatibility