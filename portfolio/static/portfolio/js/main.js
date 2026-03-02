// main.js – Deriv.Ed global interactions

(function() {
    // ===== CSRF TOKEN SETUP =====
    // Get token from global variable (set in base.html) or fallback
    let csrftoken = window.CSRF_TOKEN || '';

    if (!csrftoken) {
        // Fallback: try to get from cookie
        function getCookie(name) {
            let cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
            }
            return cookieValue;
        }
        csrftoken = getCookie('csrftoken');
    }

    if (csrftoken) {
        console.log('CSRF token retrieved successfully.');
        // Make jQuery include the token in every AJAX request automatically
        $.ajaxSetup({
            beforeSend: function(xhr, settings) {
                if (!/^(GET|HEAD|OPTIONS|TRACE)$/i.test(settings.type) && !this.crossDomain) {
                    xhr.setRequestHeader("X-CSRFToken", csrftoken);
                }
            }
        });
        // Also patch $.post to include token in data as fallback
        var originalPost = $.post;
        $.post = function(url, data, success, dataType) {
            if (typeof data === 'object' && data !== null) {
                data.csrfmiddlewaretoken = csrftoken;
            } else if (typeof data === 'string') {
                // If data is a query string, append token
                data += (data ? '&' : '') + 'csrfmiddlewaretoken=' + encodeURIComponent(csrftoken);
            } else {
                // No data, just token
                data = { csrfmiddlewaretoken: csrftoken };
            }
            return originalPost.call(this, url, data, success, dataType);
        };
        console.log('CSRF token setup complete.');
    } else {
        console.warn('CSRF token not found. AJAX POST requests may fail.');
    }

    // ===== DOCUMENT READY =====
    $(document).ready(function() {
        console.log("Deriv.Ed frontend fully loaded.");

        // ===== BACK TO TOP =====
        const backToTopBtn = document.getElementById('backToTopBtn');
        if (backToTopBtn) {
            window.addEventListener('scroll', function() {
                if (window.pageYOffset > 300) {
                    backToTopBtn.classList.add('show');
                } else {
                    backToTopBtn.classList.remove('show');
                }
            });
            backToTopBtn.addEventListener('click', function(e) {
                e.preventDefault();
                window.scrollTo({ top: 0, behavior: 'smooth' });
            });
        }

        // ===== SMOOTH SCROLL FOR ANCHOR LINKS =====
        document.querySelectorAll('a[href^="#"]:not([href="#"])').forEach(anchor => {
            anchor.addEventListener('click', function(e) {
                e.preventDefault();
                const target = document.querySelector(this.getAttribute('href'));
                if (target) {
                    const navbarHeight = document.querySelector('.navbar').offsetHeight;
                    const offsetTop = target.getBoundingClientRect().top + window.scrollY - navbarHeight;
                    window.scrollTo({ top: offsetTop, behavior: 'smooth' });
                }
            });
        });

        // ===== PASSWORD TOGGLE =====
        window.togglePassword = function(fieldId) {
            const field = document.getElementById(fieldId);
            const icon = field.nextElementSibling;
            if (!icon || !icon.classList.contains('password-toggle')) return;
            const isPassword = field.type === 'password';
            field.type = isPassword ? 'text' : 'password';
            icon.classList.toggle('fa-eye-slash', isPassword);
            icon.classList.toggle('fa-eye', !isPassword);
        };

        // ===== FORM SUBMIT SPINNER =====
        document.querySelectorAll('form').forEach(form => {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn && !form.hasAttribute('data-no-spinner')) {
                form.addEventListener('submit', function() {
                    setTimeout(() => {
                        submitBtn.disabled = true;
                        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading...';
                    }, 50);
                });
            }
        });

        // ===== ANIMATE ON SCROLL (data-animate) =====
        const animateElements = document.querySelectorAll('[data-animate]');
        if (animateElements.length) {
            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('animate');
                        observer.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.1 });
            animateElements.forEach(el => observer.observe(el));
        }

        // ===== CLOSE MOBILE NAVBAR ON LINK CLICK =====
        if (window.innerWidth < 992) {
            document.querySelectorAll('.navbar-nav .nav-link:not(.dropdown-toggle)').forEach(link => {
                link.addEventListener('click', () => {
                    const navbar = document.querySelector('.navbar-collapse');
                    if (navbar.classList.contains('show')) {
                        new bootstrap.Collapse(navbar).hide();
                    }
                });
            });
        }

        // ===== DROPDOWN KEEP OPEN ON INTERACTION (mobile) =====
        document.querySelectorAll('.dropdown-toggle').forEach(toggle => {
            toggle.addEventListener('click', function(e) {
                if (window.innerWidth < 992) {
                    e.preventDefault();
                    e.stopPropagation();
                    const menu = this.nextElementSibling;
                    document.querySelectorAll('.dropdown-menu.show').forEach(m => m.classList.remove('show'));
                    if (!menu.classList.contains('show')) menu.classList.add('show');
                }
            });
        });
        document.querySelectorAll('.dropdown-menu').forEach(menu => {
            menu.addEventListener('click', e => e.stopPropagation());
        });
        document.addEventListener('click', function(e) {
            if (window.innerWidth >= 992 && !e.target.closest('.dropdown')) {
                document.querySelectorAll('.dropdown-menu.show').forEach(m => m.classList.remove('show'));
            }
        });
    });
})();