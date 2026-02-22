document.addEventListener("DOMContentLoaded", function () {
  const startInput = document.getElementById("start_at");
  const endInput = document.getElementById("end_at");

  startInput.addEventListener("change", function () {
    endInput.min = startInput.value;
  });
});