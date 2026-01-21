
// Optional: Add JavaScript for enhanced interactivity

document.addEventListener('DOMContentLoaded', function() {
    // Auto-select winner based on higher score
    const scoreInputs = document.querySelectorAll('input[name="team1_score"], input[name="team2_score"]');
    
    scoreInputs.forEach(input => {
        input.addEventListener('change', function() {
            const team1Score = parseInt(document.querySelector('input[name="team1_score"]').value) || 0;
            const team2Score = parseInt(document.querySelector('input[name="team2_score"]').value) || 0;
            
            if (team1Score > team2Score) {
                document.querySelector('input[name="winner_id"][value*="team1"]').checked = true;
            } else if (team2Score > team1Score) {
                document.querySelector('input[name="winner_id"][value*="team2"]').checked = true;
            }
        });
    });
    
    // Form validation
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const requiredFields = form.querySelectorAll('[required]');
            let isValid = true;
            
            requiredFields.forEach(field => {
                if (!field.value) {
                    isValid = false;
                    field.style.borderColor = 'red';
                } else {
                    field.style.borderColor = '#ddd';
                }
            });
            
            if (!isValid) {
                e.preventDefault();
                alert('Please fill in all required fields');
            }
        });
    });
});
