/**
 * Mock handlers Setup mimicking the live API contract.
 * Standardizes mocking structure for local development.
 */

import placesFixture from "./fixtures/places.json";
import weatherFixture from "./fixtures/weather.json";
import routeFixture from "./fixtures/route.json";
import briefingFixture from "./fixtures/briefing.json";
import evidenceFixture from "./fixtures/evidence.json";
import observationsFixture from "./fixtures/observations.json";

export interface MockConfig {
  delayMs?: number;
  forceErrorStatus?: number;
}

export class MockPredSeaAPI {
  private config: MockConfig;

  constructor(config: MockConfig = {}) {
    this.config = {
      delayMs: 0,
      ...config
    };
  }

  private async handleDelay(): Promise<void> {
    if (this.config.delayMs && this.config.delayMs > 0) {
      await new Promise(resolve => setTimeout(resolve, this.config.delayMs));
    }
  }

  private checkError(): void {
    if (this.config.forceErrorStatus && this.config.forceErrorStatus >= 400) {
      const error: any = new Error(`Forced Mock Error ${this.config.forceErrorStatus}`);
      error.status = this.config.forceErrorStatus;
      error.detail = `API Exception forced with status ${this.config.forceErrorStatus}`;
      throw error;
    }
  }

  async searchPlaces(): Promise<typeof placesFixture> {
    await this.handleDelay();
    this.checkError();
    return placesFixture;
  }

  async getPlaceWeather(placeId: string): Promise<typeof weatherFixture> {
    await this.handleDelay();
    this.checkError();
    if (placeId !== "eze") {
      const error: any = new Error("Unknown place ID");
      error.status = 404;
      error.detail = `Place ID '${placeId}' not found`;
      throw error;
    }
    return weatherFixture;
  }

  async getRoute(origin: string, destination: string): Promise<typeof routeFixture> {
    await this.handleDelay();
    this.checkError();
    return routeFixture;
  }

  async getRouteBriefing(routeId: string): Promise<typeof briefingFixture> {
    await this.handleDelay();
    this.checkError();
    return briefingFixture;
  }

  async getRouteEvidence(routeId: string): Promise<typeof evidenceFixture> {
    await this.handleDelay();
    this.checkError();
    return evidenceFixture;
  }

  async getObservations(): Promise<typeof observationsFixture> {
    await this.handleDelay();
    this.checkError();
    return observationsFixture;
  }
}
