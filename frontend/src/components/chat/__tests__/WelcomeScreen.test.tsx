import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { WelcomeScreen } from "../WelcomeScreen";

describe("WelcomeScreen", () => {
  const onExample = vi.fn();

  beforeEach(() => onExample.mockClear());

  const renderWelcome = () => render(<MemoryRouter><WelcomeScreen onExample={onExample} /></MemoryRouter>);

  it("renders the title", () => {
    renderWelcome();
    expect(screen.getByRole("heading", { name: "Analysis" })).toBeInTheDocument();
  });

  it("renders capability chips", () => {
    renderWelcome();
    expect(screen.getByText("Primary-source research")).toBeInTheDocument();
    expect(screen.getByText("Investment committees")).toBeInTheDocument();
    expect(screen.getByText("Portfolio diagnostics")).toBeInTheDocument();
  });

  it("renders example categories", () => {
    renderWelcome();
    expect(screen.getByText("Company Research")).toBeInTheDocument();
    expect(screen.getByText("Investment Team")).toBeInTheDocument();
    expect(screen.getByText("Analysis Swarm")).toBeInTheDocument();
  });

  it("calls onExample with prompt when an example button is clicked", async () => {
    renderWelcome();
    const user = userEvent.setup();
    await user.click(screen.getByText("Company Research"));
    expect(onExample).toHaveBeenCalledTimes(1);
    expect(onExample).toHaveBeenCalledWith(
      expect.stringContaining("evidence-first equity analyst"),
    );
  });

  it("renders the helper text", () => {
    renderWelcome();
    expect(screen.getByText(/Ask about a company, sector, portfolio/)).toBeInTheDocument();
    expect(screen.getByText("How do you want to work?")).toBeInTheDocument();
  });
});
