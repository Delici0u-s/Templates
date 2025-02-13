#include <glad/glad.h>

#include <GLFW/glfw3.h>
#include <iostream>

// Callback to adjust viewport when resizing the window
void framebuffer_size_callback([[maybe_unused]] GLFWwindow *window, int width,
                               int height) {
  glViewport(0, 0, width, height);
}

int main() {
  // Initialize GLFW
  if (!glfwInit()) {
    std::cerr << "Failed to initialize GLFW\n";
    return -1;
  }

  // Set OpenGL version to 3.3 Core
  glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
  glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
  glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);

  // Create a window
  GLFWwindow *window =
      glfwCreateWindow(800, 600, "LearnOpenGL", nullptr, nullptr);
  if (!window) {
    std::cerr << "Failed to create GLFW window\n";
    glfwTerminate();
    return -1;
  }

  glfwMakeContextCurrent(window);
  glfwSetFramebufferSizeCallback(window, framebuffer_size_callback);

  // Initialize GLAD
  if (!gladLoadGLLoader((GLADloadproc)glfwGetProcAddress)) {
    std::cerr << "Failed to initialize GLAD\n";
    return -1;
  }

  // Main loop
  while (!glfwWindowShouldClose(window)) {
    // Clear screen
    glClear(GL_COLOR_BUFFER_BIT);

    // Swap buffers and poll events
    glfwSwapBuffers(window);
    glfwPollEvents();
  }

  // Cleanup
  glfwDestroyWindow(window);
  glfwTerminate();
  return 0;
}
