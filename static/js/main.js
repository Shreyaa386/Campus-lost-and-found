// CampusCare JavaScript Interactions

document.addEventListener('DOMContentLoaded', function () {
  // 1. Mobile navigation toggle
  const mobileToggle = document.getElementById('mobileMenuToggle');
  const navLinks = document.querySelector('.nav-links');
  if (mobileToggle && navLinks) {
    mobileToggle.addEventListener('click', function () {
      navLinks.classList.toggle('nav-mobile-open');
    });
  }

  // 2. Image upload preview
  const imageInputs = document.querySelectorAll('input[type="file"][accept*="image"]');
  imageInputs.forEach(input => {
    input.addEventListener('change', function (e) {
      const file = e.target.files[0];
      if (file) {
        // Size validation alert on client side (5MB)
        if (file.size > 5 * 1024 * 1024) {
          alert("File size exceeds 5MB limit. Please choose a smaller photo.");
          input.value = "";
          return;
        }

        const previewContainer = document.getElementById('imagePreviewContainer');
        const previewImage = document.getElementById('imagePreview');
        if (previewContainer && previewImage) {
          const reader = new FileReader();
          reader.onload = function (event) {
            previewImage.src = event.target.result;
            previewContainer.style.display = 'block';
          };
          reader.readAsDataURL(file);
        }
      }
    });
  });

  // 3. Auto-dismiss alerts after 6 seconds
  const alerts = document.querySelectorAll('.alert');
  alerts.forEach(alert => {
    setTimeout(() => {
      alert.style.transition = 'opacity 0.5s ease';
      alert.style.opacity = '0';
      setTimeout(() => alert.remove(), 500);
    }, 6000);
  });

  // 4. Role selection student_id helper text toggle on register page
  const roleSelect = document.getElementById('id_role');
  const studentIdField = document.getElementById('id_student_id');
  if (roleSelect && studentIdField) {
    const updateStudentIdLabel = () => {
      const val = roleSelect.value;
      const label = document.querySelector('label[for="id_student_id"]');
      if (label) {
        if (val === 'student') {
          label.innerHTML = 'Student ID / Roll No <span style="color:#ef4444;">*</span>';
          studentIdField.placeholder = "e.g. 2024CS105";
        } else if (val === 'faculty') {
          label.innerHTML = 'Faculty ID';
          studentIdField.placeholder = "e.g. FAC-CSE-042";
        } else {
          label.innerHTML = 'Staff / Employee ID';
          studentIdField.placeholder = "e.g. STF-8819";
        }
      }
    };
    roleSelect.addEventListener('change', updateStudentIdLabel);
    updateStudentIdLabel();
  }

  // 5. Interactive Password Show/Hide Toggle
  const passwordToggles = document.querySelectorAll('.password-toggle-btn');
  passwordToggles.forEach(btn => {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      const targetId = btn.getAttribute('data-target');
      const input = targetId ? document.getElementById(targetId) : btn.previousElementSibling;
      if (input) {
        const isPassword = input.type === 'password';
        input.type = isPassword ? 'text' : 'password';
        const icon = btn.querySelector('i');
        if (icon) {
          if (isPassword) {
            icon.classList.remove('fa-eye');
            icon.classList.add('fa-eye-slash');
            btn.setAttribute('aria-label', 'Hide password');
          } else {
            icon.classList.remove('fa-eye-slash');
            icon.classList.add('fa-eye');
            btn.setAttribute('aria-label', 'Show password');
          }
        }
      }
    });
  });

  // 6. Auth Form Submission Loading State
  const authForms = document.querySelectorAll('.auth-submit-form');
  authForms.forEach(form => {
    form.addEventListener('submit', function () {
      const submitBtn = form.querySelector('.auth-submit-btn');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.classList.add('btn-loading');
        const originalText = submitBtn.getAttribute('data-loading-text') || 'Processing...';
        submitBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${originalText}`;
      }
    });
  });

  // 7. Global Permanent Sidebar Drawer (Mobile & Responsive)
  const sidebar = document.getElementById('dashboardSidebar');
  const sidebarToggleBtn = document.getElementById('sidebarToggleBtn');
  const sidebarCloseBtn = document.getElementById('sidebarCloseBtn');
  const sidebarOverlay = document.getElementById('sidebarOverlay');

  function openSidebar() {
    if (sidebar) sidebar.classList.add('show');
    if (sidebarOverlay) sidebarOverlay.classList.add('show');
    document.body.classList.add('sidebar-open');
  }
  function closeSidebar() {
    if (sidebar) sidebar.classList.remove('show');
    if (sidebarOverlay) sidebarOverlay.classList.remove('show');
    document.body.classList.remove('sidebar-open');
  }

  if (sidebarToggleBtn) sidebarToggleBtn.addEventListener('click', openSidebar);
  if (sidebarCloseBtn) sidebarCloseBtn.addEventListener('click', closeSidebar);
  if (sidebarOverlay) sidebarOverlay.addEventListener('click', closeSidebar);

  // 8. Campus Selector Dropdown
  const campusBtn = document.getElementById('campusSelectorBtn');
  const campusDropdown = document.getElementById('campusSelectorDropdown');
  // 9. User Profile Dropdown
  const userBtn = document.getElementById('headerUserBtn');
  const userDropdown = document.getElementById('headerUserDropdown');

  if (campusBtn && campusDropdown) {
    campusBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      campusDropdown.classList.toggle('show');
      if (userDropdown) userDropdown.classList.remove('show');
    });
  }

  if (userBtn && userDropdown) {
    userBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      userDropdown.classList.toggle('show');
      if (campusDropdown) campusDropdown.classList.remove('show');
    });
  }

  // Close dropdowns on outside click or Escape key
  document.addEventListener('click', function() {
    if (campusDropdown) campusDropdown.classList.remove('show');
    if (userDropdown) userDropdown.classList.remove('show');
  });

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      if (campusDropdown) campusDropdown.classList.remove('show');
      if (userDropdown) userDropdown.classList.remove('show');
      closeSidebar();
    }
  });
});

