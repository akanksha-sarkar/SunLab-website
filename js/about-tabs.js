document.addEventListener('DOMContentLoaded', function () {
    var section = document.querySelector('.about-section');
    if (!section) {
        return;
    }

    section.querySelectorAll('.about-tab').forEach(function (tab) {
        tab.addEventListener('click', function () {
            var targetId = tab.getAttribute('data-about-tab');

            section.querySelectorAll('.about-tab').forEach(function (item) {
                item.classList.remove('active');
                item.setAttribute('aria-selected', 'false');
            });

            section.querySelectorAll('.about-tab-panel').forEach(function (panel) {
                panel.classList.remove('active');
                panel.hidden = true;
            });

            tab.classList.add('active');
            tab.setAttribute('aria-selected', 'true');

            var panel = document.getElementById(targetId);
            if (panel) {
                panel.classList.add('active');
                panel.hidden = false;
            }
        });
    });
});
