/**************** LANGUAGE HANDLING ****************/
let currentLang = localStorage.getItem("lang") || "en";
let TRANSLATIONS = {};

function t(key, fallback = "") {
    return TRANSLATIONS[key] || fallback;
}

async function loadLanguage(lang) {
    try {
        const res = await fetch(`/lang/${lang}.json`, { cache: "no-store" });
        if (!res.ok) return;

        TRANSLATIONS = await res.json();

        document.querySelectorAll("[data-key]").forEach(el => {
            const key = el.dataset.key;
            el.textContent = t(key, el.textContent);
        });
    } catch (e) {
        console.error("Language load error", e);
    }
}

function setLanguage(lang) {
    currentLang = lang;
    localStorage.setItem("lang", lang);
    loadLanguage(lang);
    updateLangUI(lang);
}

function updateLangUI(lang) {
    document.querySelector("#lang-en")?.classList.toggle("active", lang === "en");
    document.querySelector("#lang-ta")?.classList.toggle("active", lang === "ta");
}

if (typeof passwordHint !== "undefined") {
    passwordHint.innerText = TRANSLATIONS.password_hint || "";
}


/**************** NAVBAR & POPUP ****************/
const navbarMenu = document.querySelector(".navbar .links");
const hamburgerBtn = document.querySelector(".hamburger-btn");
const hideMenuBtn = navbarMenu?.querySelector(".close-btn");

const showPopupBtn = document.querySelector(".login-btn");
const formPopup = document.querySelector(".form-popup");
const hidePopupBtn = formPopup?.querySelector(".close-btn");

const switchLinks = formPopup?.querySelectorAll(".bottom-link a");

hamburgerBtn?.addEventListener("click", () => {
    navbarMenu.classList.toggle("show-menu");
});

hideMenuBtn?.addEventListener("click", () => {
    navbarMenu.classList.remove("show-menu");
});

showPopupBtn?.addEventListener("click", () => {
    document.body.classList.add("show-popup");
    setTimeout(() => loadLanguage(currentLang), 150);

});


hidePopupBtn?.addEventListener("click", () => {
    document.body.classList.remove("show-popup");
    loadLanguage(currentLang); // 🔥 ensure language stays consistent
});


switchLinks?.forEach(link => {
    link.addEventListener("click", (e) => {
        e.preventDefault();
        formPopup.classList[
            link.id === "signup-link" ? "add" : "remove"
        ]("show-signup");

        setTimeout(() => loadLanguage(currentLang), 100); // 🔥 IMPORTANT
    });
});


/**************** PASSWORD TOOLTIP ****************/
const signupPasswordInput = document.querySelector(".signup input[type='password']");

if (signupPasswordInput) {
    const passwordHint = document.createElement("div");
    passwordHint.className = "password-hint";
   passwordHint.innerText = "Loading...";

    signupPasswordInput.parentElement.style.position = "relative";
    signupPasswordInput.parentElement.appendChild(passwordHint);

    signupPasswordInput.addEventListener("focus", () => {
        passwordHint.innerText = TRANSLATIONS.password_hint || "";
        passwordHint.style.opacity = "1";
        passwordHint.style.visibility = "visible";
    });

    signupPasswordInput.addEventListener("blur", () => {
        passwordHint.style.opacity = "0";
        passwordHint.style.visibility = "hidden";
    });

    signupPasswordInput.addEventListener("input", () => {
        const pattern = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/;

        if (pattern.test(signupPasswordInput.value)) {
            passwordHint.style.color = "green";
            passwordHint.innerText = TRANSLATIONS.password_strong || "Strong password ✔";
        } else {
            passwordHint.style.color = "#ff4d4d";
            passwordHint.innerText = TRANSLATIONS.password_hint || "";
        }
    });
}

/**************** SIGNUP ****************/
const signupForm = document.querySelector(".signup form");

signupForm?.addEventListener("submit", async (e) => {
    e.preventDefault();

    const email = signupForm.querySelector("input[type='text']").value;
    const password = signupPasswordInput.value;
    const terms = signupForm.querySelector("#policy");

    const pattern = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/;

    if (!pattern.test(password)) {
        alert(TRANSLATIONS.password_error || "Password error");
        return;
    }

    if (!terms.checked) {
        alert(TRANSLATIONS.terms_error || "Please accept terms");
        return;
    }

    const res = await fetch("/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password })
    });

    const data = await res.json();

if (res.status === 201) {
    alert(TRANSLATIONS.signup_success || "Registered successfully");
    formPopup.classList.remove("show-signup");
} else {
    alert(data.error || TRANSLATIONS.signup_error || "Registration failed");
}

});

/**************** LOGIN ****************/
const loginForm = document.querySelector(".login form");

loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const email = loginForm.querySelector("#loginEmail").value;
    const password = loginForm.querySelector("#loginPassword").value;

    try {
        const response = await fetch("/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (response.ok) {
            // SUCCESS: Go to home page (Index), not the complaint form
            window.location.href = "/"; 
        } else {
            // ERROR: Show the message (User not found / Incorrect password)
            alert(data.error || "Login failed");
        }
    } catch (error) {
        console.error("Login Error:", error);
    }
});

/**************** FORGOT PASSWORD ****************/
const forgotLink = document.querySelector(".forgot-pass-link");

forgotLink?.addEventListener("click", async (e) => {
    e.preventDefault();

    const email = prompt(TRANSLATIONS.enter_email || "Enter registered email");
    const password = prompt(TRANSLATIONS.enter_new_password || "Enter new password");

    if (!email || !password) return;

    const res = await fetch("/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password })
    });

    const data = await res.json();
    if (res.status === 200) {
    alert(
    data.message ||
    TRANSLATIONS.password_update_success ||
    "Password updated successfully"
);

    document.body.classList.remove("show-popup");
}

});
/**************** PROTECTED ACCESS (UPDATED) ****************/
async function checkAuth() {
    const protectedSection = document.querySelector(".complaint-module");
    if (!protectedSection) return;

    try {
        const res = await fetch("/check_login", { credentials: "include" });
        if (res.status !== 200) {
            alert(TRANSLATIONS.login_required || "Please login");
            document.body.classList.add("show-popup"); // 🔥 opens login popup
            formPopup.classList.remove("show-signup"); // 🔥 force login form
        }
    } catch (err) {
        alert(TRANSLATIONS.login_required || "Please login");
        document.body.classList.add("show-popup"); // 🔥 fallback
        formPopup.classList.remove("show-signup"); // 🔥 force login form
    }
}

/**************** DOM READY ****************/
document.addEventListener("DOMContentLoaded", () => {

    // Load saved language first
    loadLanguage(currentLang);
    updateLangUI(currentLang);

    // Language switch buttons
    document.querySelector("#lang-en")?.addEventListener("click", () => {
        setLanguage("en");
    });

    document.querySelector("#lang-ta")?.addEventListener("click", () => {
        setLanguage("ta");
    });

});

/**************** RAISE COMPLAINT ACCESS CONTROL ****************/
document.addEventListener("DOMContentLoaded", () => {
    const raiseComplaintBtn = document.getElementById("raiseComplaintLink");
    if (!raiseComplaintBtn) return;

    raiseComplaintBtn.addEventListener("click", async (e) => {
        e.preventDefault();

        try {
            const res = await fetch("/check_login", {
                credentials: "include"
            });

            if (res.status !== 200) {
                alert("Please login to raise a complaint");
                document.body.classList.add("show-popup");
                formPopup.classList.remove("show-signup");
                return;
            }

            // ✅ User IS logged in -> Move to Complaint Form
            window.location.href = "/complaint_form";

        } catch (err) {
            alert("Error checking login. Please try again.");
        }
    });
});

function goAdmin() {
    window.location.href = "/admin-login";
}
